"""LLM Dispatcher — priority queue, multi-key round-robin, rate limiting.

This is the central gateway for ALL LLM calls in the application.
It replaces direct HTTP calls with:
  - Multi-key round-robin with automatic failover on 429
  - Per-key RPM rate limiting
  - Priority queuing (P0=chat > P1=job > P2=email > P3=es)
  - Daily quota tracking
  - Per-workflow model/provider routing via DB config

Usage:
    from ai.dispatcher import dispatcher
    text = dispatcher.submit("prompt", priority=0, workflow='chat')
"""
import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

# Priority constants
PRIORITY_CHAT = 0     # P0: highest — interactive, user-facing
PRIORITY_JOB = 1      # P1: job enrichment — background but important
PRIORITY_EMAIL = 2    # P2: email parsing — async, can delay
PRIORITY_ES = 3       # P3: ES generation — lowest, can defer

PRIORITY_LABELS = {0: 'CHAT', 1: 'JOB', 2: 'EMAIL', 3: 'ES'}


class _KeyState:
    """Track per-key rate limiting state."""

    def __init__(self, key_info: dict):
        self.key_id = key_info['id']
        self.provider = key_info['provider']
        self.api_key = key_info['api_key']
        self.label = key_info.get('label', '')
        self.rpm_limit = key_info.get('rpm_limit', 10)
        self.daily_limit = key_info.get('daily_limit', 1000)
        self.lock = threading.Lock()
        self.call_timestamps: deque = deque()
        self.blocked_until = 0.0  # timestamp when 429 block expires

    def is_available(self) -> bool:
        """Check if this key is available (not rate-limited or 429-blocked)."""
        now = time.time()
        if now < self.blocked_until:
            return False
        with self.lock:
            # Clean old timestamps
            while self.call_timestamps and self.call_timestamps[0] < now - 60:
                self.call_timestamps.popleft()
            return len(self.call_timestamps) < self.rpm_limit

    def record_call(self):
        """Record a call timestamp for RPM tracking."""
        with self.lock:
            self.call_timestamps.append(time.time())

    def mark_rate_limited(self, backoff_seconds: float = 30.0):
        """Mark this key as 429-blocked for a period."""
        self.blocked_until = time.time() + backoff_seconds
        logger.warning(f"[dispatcher] Key {self.key_id} ({self.label}) blocked for {backoff_seconds}s")

    def wait_for_capacity(self, timeout: float = 65.0) -> bool:
        """Wait until this key has RPM capacity. Returns False on timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_available():
                return True
            time.sleep(0.5)
        return False


class LLMDispatcher:
    """Central LLM call dispatcher with multi-key routing and priority."""

    def __init__(self):
        self._keys: list[_KeyState] = []
        self._key_index = 0  # round-robin pointer
        self._lock = threading.Lock()
        self._initialized = False

    def reload_keys(self):
        """Reload enabled API keys from the database."""
        try:
            from db.llm_settings import get_enabled_keys
            raw_keys = get_enabled_keys()
            self._keys = [_KeyState(k) for k in raw_keys]
            self._key_index = 0
            self._initialized = True
            logger.info(f"[dispatcher] Loaded {len(self._keys)} API key(s)")
        except Exception as e:
            logger.error(f"[dispatcher] Failed to load keys: {e}")
            self._keys = []
            self._initialized = True

    def _ensure_initialized(self):
        """Lazy-init: load keys on first call."""
        if not self._initialized:
            self.reload_keys()

    def _get_model_config(self, workflow: str) -> dict:
        """Get model config for a workflow from DB, with fallback defaults."""
        try:
            from db.llm_settings import get_model_config
            cfg = get_model_config(workflow)
            if cfg:
                return cfg
        except Exception as e:
            logger.debug(f"[dispatcher] Could not load model config for {workflow}: {e}")

        # Fallback to defaults — use env AI_PROVIDER
        import os
        provider = os.environ.get('AI_PROVIDER', 'deepseek')
        if provider == 'deepseek':
            default_model = 'deepseek-chat'
            default_endpoint = 'https://api.deepseek.com/v1'
        else:
            default_model = 'gemini-3-flash-preview'
            default_endpoint = ''
        return {
            'provider': provider,
            'model_name': default_model,
            'endpoint_url': default_endpoint,
            'temperature': 0.7,
            'max_tokens': 4096,
        }

    def _pick_key(self, provider: str) -> _KeyState | None:
        """Pick the next available key for the given provider using round-robin.

        Skips keys that are rate-limited, 429-blocked, or over daily quota.
        """
        self._ensure_initialized()

        if not self._keys:
            return None

        # Filter to matching provider keys
        candidates = [k for k in self._keys if k.provider == provider]
        if not candidates:
            # Fall back to any available key
            candidates = self._keys

        n = len(candidates)
        with self._lock:
            start = self._key_index % n if n else 0

        for i in range(n):
            idx = (start + i) % n
            key = candidates[idx]

            # Check daily limit
            try:
                from db.llm_settings import is_key_over_daily_limit
                if is_key_over_daily_limit(key.key_id):
                    logger.debug(f"[dispatcher] Key {key.key_id} over daily limit, skipping")
                    continue
            except Exception:
                pass

            if key.is_available():
                with self._lock:
                    self._key_index = (idx + 1) % n
                return key

        # No immediately available key — wait on the first non-daily-limited one
        for i in range(n):
            idx = (start + i) % n
            key = candidates[idx]
            try:
                from db.llm_settings import is_key_over_daily_limit
                if is_key_over_daily_limit(key.key_id):
                    continue
            except Exception:
                pass
            if key.wait_for_capacity(timeout=30):
                with self._lock:
                    self._key_index = (idx + 1) % n
                return key

        return None

    def is_configured(self) -> bool:
        """Check if any API keys are available."""
        self._ensure_initialized()
        if self._keys:
            return True
        # Fallback: check env vars
        import os
        return bool(os.environ.get('DEEPSEEK_API_KEY', '') or os.environ.get('GEMINI_API_KEY', ''))

    def submit(self, prompt: str, priority: int = 2, workflow: str = 'chat',
               temperature: float = None, max_tokens: int = None,
               model: str = None) -> str:
        """Submit an LLM request through the dispatcher.

        Args:
            prompt: The prompt text.
            priority: 0 (chat) to 3 (es). Lower = higher priority.
            workflow: One of 'chat', 'email', 'job', 'es'.
            temperature: Override temperature (None = use workflow config).
            max_tokens: Override max tokens (None = use workflow config).
            model: Override model name (None = use workflow config).

        Returns:
            Generated text, or empty string on failure.
        """
        self._ensure_initialized()

        # Get workflow-specific model config
        cfg = self._get_model_config(workflow)
        provider = cfg.get('provider', 'deepseek')
        model_name = model or cfg.get('model_name', 'deepseek-chat')
        endpoint = cfg.get('endpoint_url', '')
        temp = temperature if temperature is not None else cfg.get('temperature', 0.7)
        tokens = max_tokens if max_tokens is not None else cfg.get('max_tokens', 4096)

        # Get the adapter
        from ai.adapters import get_adapter, RateLimitError
        adapter = get_adapter(provider)

        # If we have keys in DB, use multi-key routing
        if self._keys:
            return self._submit_with_keys(
                adapter, prompt, provider, model_name, endpoint,
                temp, tokens, priority
            )

        # Fallback: use env var key (backward compatibility)
        import os
        # Pick the right env key based on provider
        if provider == 'deepseek':
            env_key = os.environ.get('DEEPSEEK_API_KEY', '')
            if not endpoint:
                endpoint = 'https://api.deepseek.com/v1'
        else:
            env_key = os.environ.get('GEMINI_API_KEY', '')
        if not env_key:
            # Try the other key as last resort
            env_key = os.environ.get('DEEPSEEK_API_KEY', '') or os.environ.get('GEMINI_API_KEY', '')
        if not env_key:
            logger.warning("[dispatcher] No API keys configured")
            return ''

        try:
            return adapter.generate(prompt, env_key, model_name, endpoint, temp, tokens)
        except RateLimitError:
            logger.warning("[dispatcher] Rate limited on env key, waiting 15s")
            time.sleep(15)
            try:
                return adapter.generate(prompt, env_key, model_name, endpoint, temp, tokens)
            except RateLimitError:
                logger.warning("[dispatcher] Still rate limited after retry, giving up")
                return ''
            except Exception:
                return ''
        except Exception as e:
            logger.error(f"[dispatcher] Error with env key: {e}")
            return ''

    def _submit_with_keys(self, adapter, prompt: str, provider: str,
                          model: str, endpoint: str, temperature: float,
                          max_tokens: int, priority: int) -> str:
        """Try to submit using DB-managed keys with failover."""
        from ai.adapters import RateLimitError

        max_retries = min(len(self._keys), 3)
        last_error = None

        for attempt in range(max_retries):
            key = self._pick_key(provider)
            if key is None:
                logger.warning(f"[dispatcher] No available key for {provider} "
                               f"(attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    time.sleep(5)
                continue

            key.record_call()

            try:
                result = adapter.generate(
                    prompt, key.api_key, model, endpoint, temperature, max_tokens
                )

                # Track usage
                try:
                    from db.llm_settings import increment_usage
                    increment_usage(key.key_id)
                except Exception as e:
                    logger.debug(f"[dispatcher] Usage tracking error: {e}")

                label = f"P{priority}({PRIORITY_LABELS.get(priority, '?')})"
                logger.info(f"[dispatcher] {label} → key={key.key_id} model={model} OK")
                return result

            except RateLimitError:
                key.mark_rate_limited(backoff_seconds=30)
                logger.warning(f"[dispatcher] Key {key.key_id} rate-limited, "
                               f"trying next key (attempt {attempt + 1})")
                last_error = "rate_limited"
                continue

            except Exception as e:
                logger.error(f"[dispatcher] Key {key.key_id} error: {e}")
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(2)
                continue

        logger.error(f"[dispatcher] All keys exhausted. Last error: {last_error}")
        return ''

    def get_status(self) -> dict:
        """Get dispatcher status for the settings page."""
        self._ensure_initialized()
        try:
            from db.llm_settings import get_total_daily_calls, get_daily_usage
            total_calls = get_total_daily_calls()
            usage = get_daily_usage()
        except Exception:
            total_calls = 0
            usage = []

        return {
            'total_keys': len(self._keys),
            'active_keys': sum(1 for k in self._keys if k.is_available()),
            'today_calls': total_calls,
            'per_key_usage': usage,
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

dispatcher = LLMDispatcher()

"""AI package — LLM integration for the Shukatsu Agent.

Provides the core LLM calling interface used by all AI sub-modules
(chat_agent, email_parser, es_writer, job_enricher).

The actual LLM calls are routed through the dispatcher which handles
multi-key round-robin, rate limiting, priority queuing, and failover.

Usage:
    from ai import call_llm, is_ai_configured, clean_json_response
"""
import json
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()

# Default LLM model — configurable via AI_PROVIDER env
# DeepSeek V3: https://platform.deepseek.com/docs
# Gemini: https://ai.google.dev/gemini-api/docs/models
DEFAULT_MODEL = os.environ.get('AI_PROVIDER', 'deepseek') == 'gemini' and 'gemini-3-flash-preview' or 'deepseek-chat'
DEFAULT_PROVIDER = os.environ.get('AI_PROVIDER', 'deepseek')
# Backward compat alias
GEMINI_MODEL = DEFAULT_MODEL


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


def is_ai_configured() -> bool:
    """Check if any LLM API key is available (DB keys or env var)."""
    try:
        from ai.dispatcher import dispatcher
        return dispatcher.is_configured()
    except Exception:
        return bool(os.environ.get('GEMINI_API_KEY', '') or os.environ.get('DEEPSEEK_API_KEY', ''))


def get_ai_status() -> dict:
    """Get the current AI configuration status for the settings page."""
    configured = is_ai_configured()
    try:
        from ai.dispatcher import dispatcher
        status = dispatcher.get_status()
    except Exception:
        status = {}

    env_key = os.environ.get('DEEPSEEK_API_KEY', '') or os.environ.get('GEMINI_API_KEY', '')
    provider_label = 'DeepSeek V3' if DEFAULT_PROVIDER == 'deepseek' else 'Google Gemini'
    return {
        'configured': configured,
        'model': DEFAULT_MODEL,
        'provider': provider_label,
        'api_key_set': configured,
        'api_key_preview': f"...{env_key[-4:]}" if env_key and len(env_key) >= 4 else '',
        'dispatcher': status,
    }


# ──────────────────────────────────────────────
# Core LLM Interface (backward-compatible wrapper)
# ──────────────────────────────────────────────

def call_llm(prompt: str, model: str = None, temperature: float = 0.7,
             max_tokens: int = 4096, retries: int = 2,
             priority: int = 2, workflow: str = 'chat') -> str:
    """Call the LLM and return the text response.

    Routes through the dispatcher for multi-key support and rate limiting.
    The `priority` and `workflow` params are used by the dispatcher for
    routing and quota management.

    Args:
        prompt: The user prompt text.
        model: Model name override (None = use workflow config).
        temperature: Sampling temperature (0.0 - 1.0).
        max_tokens: Maximum output tokens.
        retries: Number of retry attempts on transient errors.
        priority: 0 (chat) to 3 (es). Lower = higher priority.
        workflow: One of 'chat', 'email', 'job', 'es'.

    Returns:
        The generated text content, or empty string on failure.
    """
    try:
        from ai.dispatcher import dispatcher
        for attempt in range(retries + 1):
            result = dispatcher.submit(
                prompt,
                priority=priority,
                workflow=workflow,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
            )
            if result:
                return result
            if attempt < retries:
                import time
                wait = min(2 ** attempt * 3, 15)
                logger.info(f"[ai] Retry {attempt + 1}/{retries}, waiting {wait}s")
                time.sleep(wait)
        return ''
    except Exception as e:
        logger.error(f"[ai] call_llm error: {e}")
        return ''


# ──────────────────────────────────────────────
# JSON Utilities
# ──────────────────────────────────────────────

def clean_json_response(raw: str) -> str:
    """Clean LLM response to extract valid JSON.

    Strips markdown code fences, extra whitespace, and common
    LLM response artifacts that break JSON parsing.
    """
    if not raw:
        return ''

    text = raw.strip()

    # Remove markdown code block wrappers
    if text.startswith('```'):
        # Remove opening fence (with optional language tag)
        text = re.sub(r'^```(?:json|JSON)?\s*\n?', '', text)
        # Remove closing fence
        text = re.sub(r'\n?```\s*$', '', text)

    text = text.strip()

    # Try to find JSON object or array
    # Look for { ... } or [ ... ]
    obj_match = re.search(r'(\{.*\})', text, re.DOTALL)
    arr_match = re.search(r'(\[.*\])', text, re.DOTALL)

    if obj_match:
        return obj_match.group(1)
    if arr_match:
        return arr_match.group(1)

    return text


# ──────────────────────────────────────────────
# Module-level logging on import
# ──────────────────────────────────────────────

if os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('GEMINI_API_KEY'):
    logger.info(f"[ai] {DEFAULT_PROVIDER} env key configured (model: {DEFAULT_MODEL})")
else:
    logger.info("[ai] No env key — will use DB-managed keys via dispatcher")

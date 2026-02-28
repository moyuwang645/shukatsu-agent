"""LLM Adapters — unified interface for calling different LLM providers.

Each adapter implements the same `generate()` interface so the dispatcher
can transparently route requests to Gemini, OpenAI-compatible, or any
future provider without changing calling code.
"""
import json
import logging
import time
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """Abstract base for all LLM provider adapters."""

    provider_name: str = 'base'

    @abstractmethod
    def generate(self, prompt: str, api_key: str, model: str,
                 endpoint_url: str = '', temperature: float = 0.7,
                 max_tokens: int = 4096) -> str:
        """Generate text from a prompt.

        Args:
            prompt: The user prompt.
            api_key: Decrypted API key.
            model: Model name (e.g. 'gemini-3-flash-preview').
            endpoint_url: Custom API base URL (empty = use provider default).
            temperature: Sampling temperature.
            max_tokens: Max output tokens.

        Returns:
            Generated text string, or empty string on failure.
        """
        ...


class GeminiAdapter(BaseAdapter):
    """Google Gemini API adapter (generativelanguage REST API)."""

    provider_name = 'gemini'
    DEFAULT_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'

    def generate(self, prompt: str, api_key: str, model: str = 'gemini-3-flash-preview',
                 endpoint_url: str = '', temperature: float = 0.7,
                 max_tokens: int = 4096) -> str:
        base = endpoint_url.rstrip('/') if endpoint_url else self.DEFAULT_BASE_URL
        url = f"{base}/models/{model}:generateContent?key={api_key}"

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=60)

            if resp.status_code == 429:
                raise RateLimitError(f"Gemini 429: {resp.text[:200]}")

            resp.raise_for_status()
            data = resp.json()

            candidates = data.get('candidates', [])
            if candidates:
                parts = candidates[0].get('content', {}).get('parts', [])
                if parts:
                    text = parts[0].get('text', '')
                    logger.debug(f"[gemini] Response: {len(text)} chars")
                    return text

                if candidates[0].get('finishReason') == 'SAFETY':
                    logger.warning("[gemini] Response blocked by safety filter")
                    return ''

            logger.warning(f"[gemini] No text in response: {json.dumps(data)[:200]}")
            return ''

        except RateLimitError:
            raise
        except requests.exceptions.Timeout:
            logger.warning("[gemini] Request timeout")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"[gemini] HTTP error: {e}")
            raise
        except Exception as e:
            logger.error(f"[gemini] Unexpected error: {e}")
            return ''


class OpenAICompatAdapter(BaseAdapter):
    """OpenAI Chat Completions API adapter.

    Works with OpenAI, DeepSeek, and any OpenAI-compatible endpoint.
    """

    provider_name = 'openai'
    DEFAULT_BASE_URL = 'https://api.openai.com/v1'

    def generate(self, prompt: str, api_key: str, model: str = 'gpt-4o-mini',
                 endpoint_url: str = '', temperature: float = 0.7,
                 max_tokens: int = 4096) -> str:
        base = endpoint_url.rstrip('/') if endpoint_url else self.DEFAULT_BASE_URL
        url = f"{base}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)

            if resp.status_code == 429:
                raise RateLimitError(f"OpenAI 429: {resp.text[:200]}")

            resp.raise_for_status()
            data = resp.json()

            choices = data.get('choices', [])
            if choices:
                text = choices[0].get('message', {}).get('content', '')
                logger.debug(f"[openai] Response: {len(text)} chars")
                return text

            logger.warning(f"[openai] No choices in response: {json.dumps(data)[:200]}")
            return ''

        except RateLimitError:
            raise
        except requests.exceptions.Timeout:
            logger.warning("[openai] Request timeout")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"[openai] HTTP error: {e}")
            raise
        except Exception as e:
            logger.error(f"[openai] Unexpected error: {e}")
            return ''


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """Raised when a 429 rate limit response is received."""
    pass


# ---------------------------------------------------------------------------
# Adapter factory
# ---------------------------------------------------------------------------

_ADAPTERS = {
    'gemini': GeminiAdapter,
    'openai': OpenAICompatAdapter,
    'deepseek': OpenAICompatAdapter,  # DeepSeek uses OpenAI-compatible API
}


def get_adapter(provider: str) -> BaseAdapter:
    """Get an adapter instance for the given provider name.

    Args:
        provider: One of 'gemini', 'openai', 'deepseek'.

    Returns:
        BaseAdapter instance.

    Raises:
        ValueError: If the provider is not recognized.
    """
    cls = _ADAPTERS.get(provider.lower())
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}. "
                         f"Available: {list(_ADAPTERS.keys())}")
    return cls()

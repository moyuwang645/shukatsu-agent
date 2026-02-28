"""Backward-compatible shim — re-exports everything from the new ai/ package.

All existing code that does ``from ai_parser import X`` continues to work
without any changes.  New code should import directly from ``ai`` or ``ai.*``.
"""
# Core LLM interface
from ai import (  # noqa: F401
    call_llm as _call_llm,
    is_ai_configured,
    get_ai_status,
    clean_json_response as _clean_json_response,
    GEMINI_MODEL,
)

# Email parser
from ai.email_parser import parse_email_with_ai  # noqa: F401

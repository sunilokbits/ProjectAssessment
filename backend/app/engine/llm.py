"""Optional Claude integration.

Every AI feature has a deterministic fallback, so the platform works without
credentials. AI output is always treated as a *suggestion* that a human confirms.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..config import get_settings

log = logging.getLogger(__name__)


def available() -> bool:
    mode = os.getenv("PAT_AI_ENABLED", "auto").lower()
    if mode == "false":
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    if mode == "true":
        return True
    return any(os.getenv(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))


def complete_json(system: str, user: str, schema: dict[str, Any], max_tokens: int = 16000) -> dict[str, Any] | None:
    """Single structured-output call. Returns None on any failure (caller falls back)."""
    if not available():
        return None
    import anthropic

    try:
        client = anthropic.Anthropic()
        resp = client.beta.messages.create(
            model=get_settings().ai_model,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIConnectionError as e:
        log.warning("Claude unreachable, using deterministic fallback: %s", e)
        return None
    except anthropic.RateLimitError as e:
        log.warning("Claude rate-limited, using deterministic fallback: %s", e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s, using deterministic fallback: %s", e.status_code, e)
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("Claude stopped with %s; using deterministic fallback", resp.stop_reason)
        return None
    text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned non-JSON output; using deterministic fallback")
        return None

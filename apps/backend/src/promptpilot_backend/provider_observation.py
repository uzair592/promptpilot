"""Optional, credential-free observation of analysis and question provider attempts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .config import get_settings

Purpose = Literal["analysis", "question"]
RequestOutcome = Literal["not_attempted", "succeeded", "failed"]
FallbackReason = Literal[
    "not_configured", "provider_failed", "invalid_question", "duplicate_question"
]


@dataclass(frozen=True)
class ProviderCallObservation:
    purpose: Purpose
    provider: str | None
    model: str | None
    request_hash: str | None
    started_at: datetime | None
    finished_at: datetime | None
    latency_ms: int | None
    request_outcome: RequestOutcome
    service_result: Literal["ai", "fallback", "error"]
    fallback_reason: FallbackReason | None = None
    error_type: str | None = None


ProviderObserver = Callable[[ProviderCallObservation], None]


def sanitized_request_hash(purpose: Purpose, model: str | None, material: object) -> str:
    """Hash only request content and model, never URL, headers, or credentials."""

    payload = json.dumps(
        {"purpose": purpose, "model": model, "material": material},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def safe_provider_label(value: str | None) -> str | None:
    if value is None:
        return None
    secret = get_settings().llm_api_key
    return value.replace(secret, "[REDACTED]") if secret else value


def notify_observer(observer: ProviderObserver | None, event: ProviderCallObservation) -> None:
    if observer is None:
        return
    try:
        observer(event)
    except Exception:
        # Observation is optional and must never alter product behavior.
        pass

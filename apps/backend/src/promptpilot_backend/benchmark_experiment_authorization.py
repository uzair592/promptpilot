"""External launch-authorization boundary for a future live benchmark run.

This module deliberately cannot manufacture human approval.

It records authorization *claims* that must be supplied from outside this
repository and verifies only their presence, shape, and binding to a frozen
protocol. It never asserts that a claim is authentic, because software cannot
establish authenticity. Nothing here constructs an authorization: there is no
factory, no default, no environment variable, and no CLI flag that synthesises
one. A caller must present an artifact a human actually issued elsewhere.

This is deliberately a different concept from
``production_benchmark_protocol.HumanApprovalBoundary``. That boundary refuses
to accept ``externally_verified=True`` at all, because the validator cannot
verify it. This module models the artifact a stakeholder issues out of band and
records a fail-closed gate around it. Presence of the artifact is a
*precondition*, never a proof of a human identity, a signature, or consent.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .benchmark_fixtures import AwareISODateTime
from .production_benchmark_protocol import Sha256

# A local file, relative path, or bare filename could be checked into the
# repository and thereby "authorize" itself. Only opaque external references
# are acceptable evidence pointers.
_EXTERNAL_SCHEMES = frozenset({"https", "http", "urn", "mailto", "did"})
_PLACEHOLDER = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:tbd|unknown|later|placeholder|example\.com|test|none|dummy|n/?a)"
    r"(?:$|[^a-z0-9])"
)
_PLACEHOLDER_FIELDS = frozenset(
    {"authorization_id", "issued_by_reference", "evidence_reference", "authorization_notes"}
)


class AuthorizationError(ValueError):
    """Raised when external launch authorization is absent, malformed, or unbound."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require_external_reference(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("External reference must be a string")
    candidate = value.strip()
    if not candidate:
        raise ValueError("External reference must not be blank")
    parsed = urlparse(candidate)
    if not parsed.scheme:
        raise ValueError(
            "External reference must carry a scheme such as https, urn, mailto, or did"
        )
    if parsed.scheme.casefold() not in _EXTERNAL_SCHEMES:
        raise ValueError("External reference scheme is not an external authorization scheme")
    if parsed.scheme.casefold() == "http":
        raise ValueError("External authorization references must not use insecure http")
    return candidate


ExternalAuthorizationReference = Annotated[
    str,
    StringConstraints(strict=True, max_length=400),
    BeforeValidator(_require_external_reference),
]


class StrictAuthorizationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class LiveLaunchAuthorization(StrictAuthorizationModel):
    """An externally issued authorization claim for one frozen protocol.

    This record is a *claim document*. The application validates its shape and
    its binding to a protocol hash; it can never upgrade it into a verified
    fact. There is deliberately no ``verified`` field: adding a boolean here
    would let software manufacture the very approval this boundary protects.

    Every field is required, so a partially completed authorization cannot be
    presented. ``provider_authorized`` and ``spending_authorized`` are literal
    ``True`` so that a missing or negative grant fails closed at parse time
    instead of defaulting to "no" and being silently ignored downstream.
    """

    authorization_version: Literal["v1"]
    authorization_id: Annotated[str, StringConstraints(strict=True, min_length=4, max_length=160)]
    issued_by_reference: ExternalAuthorizationReference
    issued_at: AwareISODateTime
    protocol_sha256: Sha256
    provider_authorized: Literal[True]
    spending_authorized: Literal[True]
    authorized_provider: Annotated[
        str, StringConstraints(strict=True, min_length=2, max_length=120)
    ]
    authorized_model: Annotated[str, StringConstraints(strict=True, min_length=2, max_length=240)]
    maximum_spend: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    spend_currency: Annotated[
        str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")
    ]
    evidence_reference: ExternalAuthorizationReference
    authorization_notes: Annotated[
        str, StringConstraints(strict=True, max_length=2000)
    ] = ""

    @model_validator(mode="before")
    @classmethod
    def reject_placeholders(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for field in _PLACEHOLDER_FIELDS:
                candidate = value.get(field)
                if isinstance(candidate, str) and _PLACEHOLDER.search(candidate):
                    raise ValueError(
                        "Authorization fields must not contain placeholder or dummy values"
                    )
        return value

    @model_validator(mode="after")
    def bind_to_protocol(self) -> LiveLaunchAuthorization:
        if self.protocol_sha256 == "0" * 64:
            raise ValueError("Authorization must bind to a real protocol hash")
        return self

    def assert_applies_to(self, protocol_sha256: str) -> None:
        if self.protocol_sha256 != protocol_sha256:
            raise AuthorizationError(
                "authorization_protocol_mismatch",
                "Launch authorization does not apply to this frozen protocol",
            )

    def assert_covers_provider(self, provider: str, model: str) -> None:
        if (self.authorized_provider, self.authorized_model) != (provider, model):
            raise AuthorizationError(
                "authorization_provider_mismatch",
                "Launch authorization does not cover this provider and model",
            )


class LaunchGateBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class LaunchGateReport(BaseModel):
    """Fail-closed readiness report. ``ready`` requires every gate to pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_locked: bool
    fixtures_live_eligible: bool
    fixture_ids: tuple[str, ...]
    authorization_present: bool
    authorization_binds_protocol: bool
    provider_authorized: bool
    spending_authorized: bool
    provider_model_authorized: bool
    ready: bool
    blockers: tuple[LaunchGateBlocker, ...]
    software_verification_limit: str

    @property
    def admitted(self) -> bool:
        return self.ready


_SOFTWARE_LIMIT = (
    "Software verifies only the presence, shape, and protocol binding of an "
    "externally issued authorization. Authenticity of the issuer, any signature, "
    "and any consent remain unverified claims requiring out-of-band human "
    "confirmation."
)


def evaluate_launch_gate(
    *,
    protocol_locked: bool,
    fixture_ids: Sequence[str],
    live_eligible_fixture_ids: Sequence[str],
    protocol_sha256: str,
    authorization: LiveLaunchAuthorization | None,
    target_provider: str,
    target_model: str,
) -> LaunchGateReport:
    """Compute live-launch readiness without ever manufacturing authorization."""

    requested = tuple(fixture_ids)
    eligible = tuple(live_eligible_fixture_ids)
    authorization_present = authorization is not None
    binds = False
    provider_ok = False
    spending_ok = False
    provider_model_ok = False
    if authorization is not None:
        binds = authorization.protocol_sha256 == protocol_sha256
        provider_ok = authorization.provider_authorized is True
        spending_ok = authorization.spending_authorized is True
        provider_model_ok = (
            binds
            and (authorization.authorized_provider, authorization.authorized_model)
            == (target_provider, target_model)
        )
    fixtures_ok = bool(requested) and set(requested) <= set(eligible)

    blockers: list[LaunchGateBlocker] = []
    if not protocol_locked:
        blockers.append(
            LaunchGateBlocker(
                code="protocol_not_locked", message="Protocol review is not locked"
            )
        )
    if not requested:
        blockers.append(
            LaunchGateBlocker(
                code="fixture_set_empty", message="No fixtures were requested"
            )
        )
    elif not fixtures_ok:
        blockers.append(
            LaunchGateBlocker(
                code="fixtures_not_live_eligible",
                message="Every selected fixture must be live-eligible",
            )
        )
    if not authorization_present:
        blockers.append(
            LaunchGateBlocker(
                code="launch_authorization_absent",
                message="No external launch authorization was supplied",
            )
        )
    else:
        if not binds:
            blockers.append(
                LaunchGateBlocker(
                    code="authorization_protocol_mismatch",
                    message="Launch authorization is bound to a different protocol",
                )
            )
        if not provider_ok:
            blockers.append(
                LaunchGateBlocker(
                    code="provider_not_authorized",
                    message="Launch authorization does not grant provider access",
                )
            )
        if not spending_ok:
            blockers.append(
                LaunchGateBlocker(
                    code="spending_not_authorized",
                    message="Launch authorization does not grant spending",
                )
            )
        if not provider_model_ok:
            blockers.append(
                LaunchGateBlocker(
                    code="authorized_provider_mismatch",
                    message="Authorized provider and model do not match the target binding",
                )
            )

    ready = not blockers
    return LaunchGateReport(
        protocol_locked=protocol_locked,
        fixtures_live_eligible=fixtures_ok,
        fixture_ids=requested,
        authorization_present=authorization_present,
        authorization_binds_protocol=binds,
        provider_authorized=provider_ok,
        spending_authorized=spending_ok,
        provider_model_authorized=provider_model_ok,
        ready=ready,
        blockers=tuple(blockers),
        software_verification_limit=_SOFTWARE_LIMIT,
    )


def parse_authorization(payload: Any) -> LiveLaunchAuthorization:
    """Parse an externally supplied authorization document."""

    try:
        return LiveLaunchAuthorization.model_validate(payload)
    except ValidationError as exc:
        raise AuthorizationError(
            "authorization_invalid", "Launch authorization is absent or malformed"
        ) from exc
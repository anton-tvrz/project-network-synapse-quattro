"""API-key authentication and role-based authorization (ADR-0005).

Lab-grade credentials: per-user static API keys mapped to roles, supplied via
the ``PRESENTATION_API_KEYS`` environment variable in the form::

    <key>:<user>:<role>,<key>:<user>:<role>,...

The auth dependency is isolated here so it can be swapped for OIDC later
without touching route handlers. Every rejected request emits an auditable
log line.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger("synapse_presentation.auth")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class Role(enum.IntEnum):
    """Presentation-layer roles, ordered by privilege."""

    VIEWER = 1
    OPERATOR = 2

    def satisfies(self, required: Role) -> bool:
        """A role satisfies any requirement at or below its privilege level."""
        return self >= required


@dataclass(frozen=True)
class Identity:
    """The authenticated caller — recorded in every workflow it initiates."""

    user: str
    role: Role


def parse_api_keys(raw: str) -> dict[str, Identity]:
    """Parse ``key:user:role`` entries into an API-key -> identity map."""
    keys: dict[str, Identity] = {}
    for raw_entry in raw.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"Malformed API key entry (want key:user:role): {entry!r}")
        key, user, role_name = parts
        try:
            role = Role[role_name.upper()]
        except KeyError:
            raise ValueError(f"Unknown role {role_name!r} for user {user!r}") from None
        if key in keys:
            raise ValueError(f"duplicate API key for user {user!r}")
        keys[key] = Identity(user=user, role=role)
    return keys


def _authenticate(request: Request, api_key: str | None) -> Identity:
    """Resolve an API key to an identity, or reject with 401."""
    if api_key is None:
        logger.warning("Request rejected: missing API key (path=%s)", request.url.path)
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    identity = request.app.state.api_keys.get(api_key)
    if identity is None:
        logger.warning("Request rejected: unknown API key (path=%s)", request.url.path)
        raise HTTPException(status_code=401, detail="Unknown API key")
    return identity


def require_role(required: Role):
    """Build a FastAPI dependency that authenticates and enforces a role."""

    def dependency(request: Request, api_key: str | None = Security(_api_key_header)) -> Identity:
        identity = _authenticate(request, api_key)
        if not identity.role.satisfies(required):
            logger.warning(
                "Request rejected: user %s (role=%s) lacks role %s (path=%s)",
                identity.user,
                identity.role.name,
                required.name,
                request.url.path,
            )
            raise HTTPException(status_code=403, detail=f"Requires {required.name.lower()} role")
        return identity

    return dependency

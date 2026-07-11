"""gNMI transport settings and device credential resolution (Issue #166).

Every gNMI connection in the project builds its transport-security kwargs
here, so TLS posture is a deployment decision (environment) instead of being
hardcoded. ``insecure`` remains the default because the local containerlab
profile is the primary target — but note that containerlab's default SR Linux
gNMI server is TLS-only, so real lab use needs ``GNMI_TLS_MODE=skip-verify``.

Credentials are resolved here — inside the process that opens the connection —
rather than passed as workflow/activity arguments, because Temporal persists
every activity input in workflow history where secrets would be readable via
the Web UI and API.

Environment variables:
    GNMI_TLS_MODE   insecure (default) | skip-verify | ca-cert
    GNMI_CA_CERT    path to the CA certificate (required for ca-cert mode)
    GNMI_USERNAME   device username (default: containerlab SR Linux "admin")
    GNMI_PASSWORD   device password (default: containerlab SR Linux default)
"""

from __future__ import annotations

import os

_LAB_DEFAULT_USER = "admin"
_LAB_DEFAULT_PASS = "NokiaSrl1!"  # noqa: S105 — containerlab SR Linux default, overridden via env


def gnmi_connection_kwargs() -> dict:
    """Transport-security kwargs for ``pygnmi.client.gNMIclient``.

    Fails loud on a malformed mode: a typo must abort the connection attempt,
    never silently fall back to plaintext.
    """
    mode = os.getenv("GNMI_TLS_MODE", "insecure").lower()
    if mode == "insecure":
        return {"insecure": True}
    if mode == "skip-verify":
        return {"skip_verify": True}
    if mode == "ca-cert":
        ca_cert = os.getenv("GNMI_CA_CERT")
        if not ca_cert:
            raise ValueError("GNMI_TLS_MODE=ca-cert requires GNMI_CA_CERT to point at the CA certificate")
        return {"path_root": ca_cert}
    raise ValueError(f"Unknown GNMI_TLS_MODE {mode!r} (expected insecure, skip-verify, or ca-cert)")


def device_credentials() -> tuple[str, str]:
    """Resolve (username, password) for device access from the environment."""
    return (
        os.getenv("GNMI_USERNAME", _LAB_DEFAULT_USER),
        os.getenv("GNMI_PASSWORD", _LAB_DEFAULT_PASS),
    )

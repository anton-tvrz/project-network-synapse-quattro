"""Shared gNMI I/O helpers for Temporal activities.

pygnmi exposes a synchronous, gRPC-backed client. Calling it directly from an
``async def`` activity blocks the worker's event loop and starves other
activity coroutines on the same worker. These helpers offload the blocking
client onto a worker thread via :func:`asyncio.to_thread` and rewrap the
narrow set of transport errors we expect from a real device into
``RuntimeError`` — Temporal then surfaces them to the workflow as activity
failures.
"""

from __future__ import annotations

import asyncio
import json

import grpc
from pygnmi.client import gNMIclient, gNMIException

from network_synapse.gnmi_settings import device_credentials, gnmi_connection_kwargs
from network_synapse.scripts.deploy_configs import deploy_config as push_via_gnmi

# Errors we expect from a gRPC/gNMI round-trip against a real device.
# Anything outside this set should bubble up unchanged — it's a programming bug.
_GNMI_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    gNMIException,
    grpc.RpcError,
    ConnectionError,
    OSError,
    TimeoutError,
)


# Paths a root-level GET response may label its updates with.
_ROOT_PATHS = frozenset({None, "", "/"})


def _extract_config_payload(result: dict, device_hostname: str) -> str:
    """Merge every root-level update in the GET response into one config dict.

    Discarding any update would produce a partial backup that silently loses
    config on rollback (Issue #164). A subtree-scoped update cannot be merged
    faithfully, so it fails loud here — at backup time, before any change is
    deployed — rather than corrupting the rollback payload.
    """
    merged: dict = {}
    saw_update = False
    for notif in result.get("notification", []):
        for update in notif.get("update", []):
            if "val" not in update:
                continue
            path = update.get("path")
            if path not in _ROOT_PATHS:
                raise RuntimeError(
                    f"gNMI GET from {device_hostname} returned non-root update path {path!r}; "
                    "refusing to build a backup that cannot be restored faithfully"
                )
            val = update["val"]
            if not isinstance(val, dict):
                raise RuntimeError(f"Unexpected gNMI GET format from {device_hostname}: {result}")
            overlap = merged.keys() & val.keys()
            if overlap:
                raise RuntimeError(
                    f"gNMI GET from {device_hostname} returned overlapping top-level keys "
                    f"{sorted(overlap)} across updates; refusing to build a backup that "
                    "would silently drop config"
                )
            merged.update(val)
            saw_update = True
    if not saw_update:
        raise RuntimeError(f"Unexpected gNMI GET format from {device_hostname}: {result}")
    return json.dumps(merged)


def _fetch_config_via_gnmi_sync(
    device_hostname: str,
    ip_address: str,
    username: str | None,
    password: str | None,
    port: int,
) -> str:
    if username is None or password is None:
        env_user, env_pass = device_credentials()
        username = username if username is not None else env_user
        password = password if password is not None else env_pass
    with gNMIclient(
        target=(ip_address, port),
        username=username,
        password=password,
        **gnmi_connection_kwargs(),
    ) as gc:
        # datatype="config" limits the GET to writable leaves; the default
        # ("all") includes operational state that SR Linux rejects on SET,
        # which broke rollback exactly when it was needed (Issue #164).
        result = gc.get(path=["/"], datatype="config")
    return _extract_config_payload(result, device_hostname)


async def fetch_config_via_gnmi(
    device_hostname: str,
    ip_address: str,
    username: str | None = None,
    password: str | None = None,
    port: int = 57400,
) -> str:
    """Fetch the running *config* (writable leaves only) via gNMI GET ``/``.

    Returns all root-level updates merged into one JSON object — a payload
    that can be pushed back verbatim as a rollback (Issue #164). Wraps
    transport errors as ``RuntimeError`` so Temporal sees a consistent
    failure type.

    Credentials default to the worker's environment (Issue #166); the explicit
    parameters exist for tests and standalone scripts, never for activity
    callers — activity arguments are persisted in Temporal history.
    """
    try:
        return await asyncio.to_thread(
            _fetch_config_via_gnmi_sync,
            device_hostname,
            ip_address,
            username,
            password,
            port,
        )
    except _GNMI_TRANSPORT_ERRORS as e:
        raise RuntimeError(f"gNMI fetch failed for {device_hostname}: {e!s}") from e


async def deploy_config_via_gnmi(
    device_hostname: str,
    ip_address: str,
    config_payload: str,
    username: str | None = None,
    password: str | None = None,
    replace: bool = False,
) -> bool:
    """Push a JSON config payload to a device via gNMI SET.

    ``replace=True`` restores the device to exactly the payload (rollbacks);
    the default merges into the existing config (deploys).
    """
    try:
        return await asyncio.to_thread(
            push_via_gnmi,
            hostname=device_hostname,
            ip_address=ip_address,
            config_payload=config_payload,
            username=username,
            password=password,
            replace=replace,
        )
    except _GNMI_TRANSPORT_ERRORS as e:
        raise RuntimeError(f"gNMI deploy failed for {device_hostname}: {e!s}") from e

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


def _extract_config_payload(result: dict, device_hostname: str) -> str:
    for notif in result.get("notification", []):
        for update in notif.get("update", []):
            if "val" in update:
                return json.dumps(update["val"])
    raise RuntimeError(f"Unexpected gNMI GET format from {device_hostname}: {result}")


def _fetch_config_via_gnmi_sync(
    device_hostname: str,
    ip_address: str,
    username: str,
    password: str,
    port: int,
) -> str:
    with gNMIclient(
        target=(ip_address, port),
        username=username,
        password=password,
        insecure=True,
    ) as gc:
        result = gc.get(path=["/"])
    return _extract_config_payload(result, device_hostname)


async def fetch_config_via_gnmi(
    device_hostname: str,
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
    port: int = 57400,
) -> str:
    """Fetch the running config from a device via gNMI GET ``/``.

    Returns the first ``val`` update as a JSON string. Wraps transport
    errors as ``RuntimeError`` so Temporal sees a consistent failure type.
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
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
) -> bool:
    """Push a JSON config payload to a device via gNMI SET."""
    try:
        return await asyncio.to_thread(
            push_via_gnmi,
            hostname=device_hostname,
            ip_address=ip_address,
            config_payload=config_payload,
            username=username,
            password=password,
        )
    except _GNMI_TRANSPORT_ERRORS as e:
        raise RuntimeError(f"gNMI deploy failed for {device_hostname}: {e!s}") from e

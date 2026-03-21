"""Infrahub GraphQL client for querying device intended state.

Provides InfrahubConfigClient — a typed client that queries Infrahub for
device, interface, and BGP session data, returning Pydantic models ready
for SR Linux config generation.

Authentication follows the same pattern as populate_sot.py:
  - If INFRAHUB_TOKEN is set, use it as X-INFRAHUB-KEY header
  - Otherwise, auto-login with default admin/infrahub credentials
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .models import BGPSessionData, DeviceConfig, DeviceData, InterfaceData

# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

QUERY_LIST_DEVICES = """
query ListDevices {
    DcimDevice {
        edges {
            node {
                name { value }
            }
        }
    }
}
"""

QUERY_DEVICE = """
query GetDevice($hostname: String!) {
    DcimDevice(name__value: $hostname) {
        edges {
            node {
                id
                name { value }
                description { value }
                management_ip { value }
                lab_node_name { value }
                role { value }
                status { value }
                asn {
                    node {
                        asn { value }
                        name { value }
                    }
                }
            }
        }
    }
}
"""

QUERY_DEVICE_INTERFACES = """
query GetDeviceInterfaces($device_ids: [ID!]) {
    InterfacePhysical(device__ids: $device_ids) {
        edges {
            node {
                id
                name { value }
                description { value }
                mtu { value }
                role { value }
                ip_addresses {
                    edges {
                        node {
                            address { value }
                        }
                    }
                }
            }
        }
    }
}
"""

MUTATION_UPDATE_DEVICE_STATUS = """
mutation UpdateDeviceStatus($data: DcimDeviceUpdateInput!) {
    DcimDeviceUpdate(data: $data) {
        ok
        object {
            id
            display_label
        }
    }
}
"""

VALID_DEVICE_STATUSES: frozenset[str] = frozenset({"active", "provisioning", "maintenance", "drained"})

QUERY_DEVICE_BGP_SESSIONS = """
query GetDeviceBGPSessions($device_ids: [ID!]) {
    RoutingBGPSession(device__ids: $device_ids) {
        edges {
            node {
                id
                description { value }
                session_type { value }
                role { value }
                status { value }
                local_as {
                    node {
                        asn { value }
                    }
                }
                remote_as {
                    node {
                        asn { value }
                    }
                }
                local_ip {
                    node {
                        address { value }
                    }
                }
                remote_ip {
                    node {
                        address { value }
                    }
                }
                peer_group {
                    node {
                        name { value }
                    }
                }
            }
        }
    }
}
"""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DeviceNotFoundError(Exception):
    """Raised when a device hostname is not found in Infrahub."""

    def __init__(self, hostname: str) -> None:
        self.hostname = hostname
        super().__init__(f"Device not found in Infrahub: {hostname}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class InfrahubConfigClient:
    """Client for querying Infrahub GraphQL API for device config data.

    Usage::

        with InfrahubConfigClient(url="http://localhost:8000") as client:
            config = client.get_device_config("spine01")
            bgp_vars = config.to_bgp_template_vars()
            iface_vars = config.to_interface_template_vars()
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
    ) -> None:
        resolved_url = url or os.getenv("INFRAHUB_URL") or "http://localhost:8000"
        self.url = resolved_url.rstrip("/")
        self.token = token or os.getenv("INFRAHUB_TOKEN", "")
        self._client: httpx.Client | None = None
        self._authenticated = False

    # -- lifecycle --

    def _get_headers(self) -> dict[str, str]:
        """Build HTTP headers with authentication."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["X-INFRAHUB-KEY"] = self.token
        return headers

    def _ensure_client(self) -> httpx.Client:
        """Lazily create httpx client, auto-login if no token."""
        if self._client is None:
            self._client = httpx.Client(headers=self._get_headers())
            if not self.token and not self._authenticated:
                self._auto_login()
        return self._client

    def _auto_login(self) -> None:
        """Authenticate with default admin credentials (same as populate_sot.py)."""
        client = self._client
        if client is None:
            return
        try:
            resp = client.post(
                f"{self.url}/api/auth/login",
                json={"username": "admin", "password": "infrahub"},
                timeout=10.0,
            )
            data = resp.json()
            if "access_token" in data:
                client.headers["Authorization"] = f"Bearer {data['access_token']}"
                self._authenticated = True
        except (httpx.HTTPError, KeyError):
            pass  # Continue without auth — local dev may not require it

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> InfrahubConfigClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- GraphQL execution --

    def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        """Execute a GraphQL query/mutation against Infrahub."""
        client = self._ensure_client()
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        resp = client.post(f"{self.url}/graphql", json=payload, timeout=30.0)
        data = resp.json()

        if data.get("errors"):
            error_msgs = [e.get("message", str(e)) for e in data["errors"]]
            raise RuntimeError(f"GraphQL errors: {'; '.join(error_msgs)}")

        result: dict[str, Any] = data.get("data", {})
        return result

    # -- query methods --

    def get_all_device_hostnames(self) -> list[str]:
        """List all device hostnames from Infrahub."""
        result = self._graphql(QUERY_LIST_DEVICES)
        edges = result.get("DcimDevice", {}).get("edges", [])
        return [edge["node"]["name"]["value"] for edge in edges]

    def list_devices(self) -> list[str]:
        """Alias for get_all_device_hostnames — returns all device hostnames."""
        return self.get_all_device_hostnames()

    def get_device(self, hostname: str) -> DeviceData:
        """Query a device by hostname. Returns parsed DeviceData."""
        # Infrahub filters with __value don't use GraphQL variables for the filter,
        # but we embed hostname safely (no injection risk for GraphQL string literals).
        result = self._graphql(QUERY_DEVICE, variables={"hostname": hostname})
        edges = result.get("DcimDevice", {}).get("edges", [])

        if not edges:
            raise DeviceNotFoundError(hostname)

        node = edges[0]["node"]
        asn_node = node.get("asn", {}).get("node")
        asn_value = asn_node["asn"]["value"] if asn_node else 0

        return DeviceData(
            id=node["id"],
            name=node["name"]["value"],
            description=node.get("description", {}).get("value", ""),
            management_ip=node.get("management_ip", {}).get("value", ""),
            lab_node_name=node.get("lab_node_name", {}).get("value", ""),
            role=node.get("role", {}).get("value", ""),
            status=node.get("status", {}).get("value", "active"),
            asn=asn_value,
        )

    def get_device_interfaces(self, device_id: str) -> list[InterfaceData]:
        """Query interfaces for a device by device ID."""
        result = self._graphql(
            QUERY_DEVICE_INTERFACES,
            variables={"device_ids": [device_id]},
        )
        edges = result.get("InterfacePhysical", {}).get("edges", [])

        interfaces = []
        for edge in edges:
            node = edge["node"]

            # Extract first IP address if present
            ip_edges = node.get("ip_addresses", {}).get("edges", [])
            ip_address = ip_edges[0]["node"]["address"]["value"] if ip_edges else None

            interfaces.append(
                InterfaceData(
                    name=node["name"]["value"],
                    description=node.get("description", {}).get("value", ""),
                    mtu=node.get("mtu", {}).get("value", 9214) or 9214,
                    role=node.get("role", {}).get("value", ""),
                    ip_address=ip_address,
                )
            )

        return interfaces

    def get_device_bgp_sessions(self, device_id: str) -> list[BGPSessionData]:
        """Query BGP sessions for a device by device ID."""
        result = self._graphql(
            QUERY_DEVICE_BGP_SESSIONS,
            variables={"device_ids": [device_id]},
        )
        edges = result.get("RoutingBGPSession", {}).get("edges", [])

        sessions = []
        for edge in edges:
            node = edge["node"]

            local_as_node = node.get("local_as", {}).get("node")
            remote_as_node = node.get("remote_as", {}).get("node")
            local_ip_node = node.get("local_ip", {}).get("node")
            remote_ip_node = node.get("remote_ip", {}).get("node")
            peer_group_node = node.get("peer_group", {}).get("node")

            sessions.append(
                BGPSessionData(
                    description=node.get("description", {}).get("value", ""),
                    session_type=node.get("session_type", {}).get("value", "EXTERNAL"),
                    role=node.get("role", {}).get("value", "backbone"),
                    local_asn=local_as_node["asn"]["value"] if local_as_node else 0,
                    remote_asn=remote_as_node["asn"]["value"] if remote_as_node else 0,
                    local_ip=local_ip_node["address"]["value"] if local_ip_node else "",
                    remote_ip=remote_ip_node["address"]["value"] if remote_ip_node else "",
                    peer_group=peer_group_node["name"]["value"] if peer_group_node else "underlay",
                )
            )

        return sessions

    def get_device_config(self, hostname: str) -> DeviceConfig:
        """Fetch complete device config: device + interfaces + BGP sessions.

        This is the main entry point — used by generate_configs.py CLI and
        the Temporal fetch_device_config activity.

        Derives router_id from the first loopback interface with an IP address.
        """
        device = self.get_device(hostname)
        interfaces = self.get_device_interfaces(device.id)
        bgp_sessions = self.get_device_bgp_sessions(device.id)

        # Derive router_id from loopback0 IP (strip /32)
        for iface in interfaces:
            if iface.role == "loopback" and iface.ip_address:
                device.router_id = iface.ip_address.split("/")[0]
                break

        if not device.router_id:
            msg = f"No loopback interface with IP found for {hostname} — cannot derive router_id"
            raise ValueError(msg)

        return DeviceConfig(
            device=device,
            interfaces=interfaces,
            bgp_sessions=bgp_sessions,
        )

    def update_device_status(self, hostname: str, new_status: str) -> DeviceData:
        """Update device status in Infrahub via GraphQL mutation.

        Resolves device ID via hostname, then issues a DcimDeviceUpdate mutation.

        Args:
            hostname: Device hostname to look up.
            new_status: Target status. Must be one of: active, provisioning,
                maintenance, drained.

        Returns:
            DeviceData of the device *before* the update (for audit logging).

        Raises:
            ValueError: If new_status is not a valid device status.
            DeviceNotFoundError: If hostname does not exist in Infrahub.
            RuntimeError: If the GraphQL mutation fails.
        """
        if new_status not in VALID_DEVICE_STATUSES:
            msg = f"Invalid device status '{new_status}'. Must be one of: {', '.join(sorted(VALID_DEVICE_STATUSES))}"
            raise ValueError(msg)

        device = self.get_device(hostname)

        result = self._graphql(
            MUTATION_UPDATE_DEVICE_STATUS,
            variables={"data": {"id": device.id, "status": {"value": new_status}}},
        )

        update_result = result.get("DcimDeviceUpdate", {})
        if not update_result.get("ok"):
            raise RuntimeError(f"Failed to update status for device '{hostname}': {result}")

        return device

    def execute_transform(self, transform_name: str, variables: dict[str, Any] | None = None) -> str:
        """Execute an Infrahub Python transform and return the result.

        Args:
            transform_name: Name of the registered transform (from .infrahub.yml).
            variables: Variables to pass to the transform's GraphQL query.

        Returns:
            Transform output as a string (typically JSON).

        Raises:
            RuntimeError: If the transform execution fails.
        """
        query = """
        query ExecuteTransform($name: String!, $params: JSON) {
            InfrahubTransformPython(transform: $name, params: $params) {
                data
            }
        }
        """
        gql_vars: dict[str, Any] = {"name": transform_name}
        if variables:
            gql_vars["params"] = variables

        result = self._graphql(query, variables=gql_vars)
        transform_result = result.get("InfrahubTransformPython", {})
        data = transform_result.get("data")
        if data is None:
            raise RuntimeError(f"Transform '{transform_name}' returned no data: {result}")
        return str(data)

"""Infrahub Resource Manager for dynamic IP and ASN allocation.

Provides InfrahubResourceManager — a client for creating and allocating from
Infrahub's built-in resource pools (CoreIPPrefixPool, CoreIPAddressPool,
CoreNumberPool).

Follows the same authentication and HTTP patterns as InfrahubConfigClient.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any

import httpx

from .models import (
    AllocationResult,
    FabricLinkAllocation,
    ProvisioningResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL mutations for pool creation
# ---------------------------------------------------------------------------

MUTATION_CREATE_IP_PREFIX_POOL = """
mutation CreateIPPrefixPool($data: CoreIPPrefixPoolCreateInput!) {
    CoreIPPrefixPoolCreate(data: $data) {
        ok
        object { id display_label }
    }
}
"""

MUTATION_CREATE_IP_ADDRESS_POOL = """
mutation CreateIPAddressPool($data: CoreIPAddressPoolCreateInput!) {
    CoreIPAddressPoolCreate(data: $data) {
        ok
        object { id display_label }
    }
}
"""

MUTATION_CREATE_NUMBER_POOL = """
mutation CreateNumberPool($data: CoreNumberPoolCreateInput!) {
    CoreNumberPoolCreate(data: $data) {
        ok
        object { id display_label }
    }
}
"""

# ---------------------------------------------------------------------------
# GraphQL queries for pool lookup
# ---------------------------------------------------------------------------

QUERY_IP_PREFIX_POOL = """
query GetIPPrefixPool($name: String!) {
    CoreIPPrefixPool(name__value: $name) {
        edges { node { id } }
    }
}
"""

QUERY_IP_ADDRESS_POOL = """
query GetIPAddressPool($name: String!) {
    CoreIPAddressPool(name__value: $name) {
        edges { node { id } }
    }
}
"""

QUERY_NUMBER_POOL = """
query GetNumberPool($name: String!) {
    CoreNumberPool(name__value: $name) {
        edges { node { id } }
    }
}
"""

# ---------------------------------------------------------------------------
# GraphQL mutations for resource allocation
# ---------------------------------------------------------------------------

MUTATION_ALLOCATE_PREFIX = """
mutation AllocatePrefix($pool_id: String!, $identifier: String, $prefix_length: Int) {
    IPPrefixPoolGetResource(
        data: {
            id: $pool_id
            identifier: $identifier
            prefix_length: $prefix_length
        }
    ) {
        ok
        node {
            id
            prefix { value }
        }
    }
}
"""

MUTATION_ALLOCATE_IP_ADDRESS = """
mutation AllocateIPAddress($pool_id: String!, $identifier: String) {
    IPAddressPoolGetResource(
        data: {
            id: $pool_id
            identifier: $identifier
        }
    ) {
        ok
        node {
            id
            address { value }
        }
    }
}
"""

MUTATION_ALLOCATE_NUMBER = """
mutation AllocateNumber($pool_id: String!, $identifier: String) {
    NumberPoolGetResource(
        data: {
            id: $pool_id
            identifier: $identifier
        }
    ) {
        ok
        node {
            id
            value
        }
    }
}
"""

# ---------------------------------------------------------------------------
# Pool type to query mapping
# ---------------------------------------------------------------------------

_POOL_QUERIES = {
    "CoreIPPrefixPool": QUERY_IP_PREFIX_POOL,
    "CoreIPAddressPool": QUERY_IP_ADDRESS_POOL,
    "CoreNumberPool": QUERY_NUMBER_POOL,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PoolNotFoundError(Exception):
    """Raised when a resource pool is not found in Infrahub."""

    def __init__(self, pool_type: str, pool_name: str) -> None:
        self.pool_type = pool_type
        self.pool_name = pool_name
        super().__init__(f"{pool_type} not found: {pool_name}")


class PoolExhaustedError(Exception):
    """Raised when a resource pool has no more resources to allocate."""

    def __init__(self, pool_name: str) -> None:
        self.pool_name = pool_name
        super().__init__(f"Pool exhausted: {pool_name}")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class InfrahubResourceManager:
    """Client for managing Infrahub resource pools and allocations.

    Usage::

        with InfrahubResourceManager(url="http://localhost:8000") as mgr:
            pool_id = mgr.create_ip_prefix_pool("fabric", "Fabric /31s", 31, [prefix_id])
            result = mgr.allocate_prefix(pool_id, 31, "spine01-leaf01")
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
        """Authenticate with default admin credentials."""
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
            pass

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> InfrahubResourceManager:
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

    # -- pool lookup --

    def get_pool_by_name(self, pool_type: str, name: str) -> str | None:
        """Look up a resource pool ID by type and name.

        Args:
            pool_type: One of CoreIPPrefixPool, CoreIPAddressPool, CoreNumberPool.
            name: Pool name to look up.

        Returns:
            Pool ID if found, None otherwise.
        """
        query = _POOL_QUERIES.get(pool_type)
        if not query:
            raise ValueError(f"Unknown pool type: {pool_type}")

        result = self._graphql(query, variables={"name": name})
        edges = result.get(pool_type, {}).get("edges", [])
        if edges:
            return edges[0]["node"]["id"]
        return None

    # -- pool creation --

    def create_ip_prefix_pool(
        self,
        name: str,
        description: str,
        default_prefix_length: int,
        resource_prefix_ids: list[str],
    ) -> str:
        """Create an IP prefix pool or return existing pool ID.

        Args:
            name: Pool name (must be unique).
            description: Human-readable description.
            default_prefix_length: Default prefix length for allocations (e.g. 31).
            resource_prefix_ids: IDs of IpamPrefix objects to use as pool resources.

        Returns:
            Pool ID.
        """
        existing = self.get_pool_by_name("CoreIPPrefixPool", name)
        if existing:
            logger.info("IP prefix pool '%s' already exists: %s", name, existing[:8])
            return existing

        data: dict[str, Any] = {
            "name": {"value": name},
            "description": {"value": description},
            "default_prefix_length": {"value": default_prefix_length},
            "resources": [{"id": pid} for pid in resource_prefix_ids],
        }
        result = self._graphql(MUTATION_CREATE_IP_PREFIX_POOL, variables={"data": data})
        create_result = result.get("CoreIPPrefixPoolCreate", {})
        if not create_result.get("ok"):
            raise RuntimeError(f"Failed to create IP prefix pool '{name}': {result}")

        pool_id: str = create_result["object"]["id"]
        logger.info("Created IP prefix pool '%s': %s", name, pool_id[:8])
        return pool_id

    def create_ip_address_pool(
        self,
        name: str,
        description: str,
        default_prefix_length: int,
        resource_prefix_ids: list[str],
    ) -> str:
        """Create an IP address pool or return existing pool ID.

        Args:
            name: Pool name (must be unique).
            description: Human-readable description.
            default_prefix_length: Default prefix length (typically 32).
            resource_prefix_ids: IDs of IpamPrefix objects to allocate from.

        Returns:
            Pool ID.
        """
        existing = self.get_pool_by_name("CoreIPAddressPool", name)
        if existing:
            logger.info("IP address pool '%s' already exists: %s", name, existing[:8])
            return existing

        data: dict[str, Any] = {
            "name": {"value": name},
            "description": {"value": description},
            "default_prefix_length": {"value": default_prefix_length},
            "resources": [{"id": pid} for pid in resource_prefix_ids],
        }
        result = self._graphql(MUTATION_CREATE_IP_ADDRESS_POOL, variables={"data": data})
        create_result = result.get("CoreIPAddressPoolCreate", {})
        if not create_result.get("ok"):
            raise RuntimeError(f"Failed to create IP address pool '{name}': {result}")

        pool_id: str = create_result["object"]["id"]
        logger.info("Created IP address pool '%s': %s", name, pool_id[:8])
        return pool_id

    def create_number_pool(
        self,
        name: str,
        description: str,
        start_range: int,
        end_range: int,
    ) -> str:
        """Create a number pool or return existing pool ID.

        Args:
            name: Pool name (must be unique).
            description: Human-readable description.
            start_range: Start of the number range (inclusive).
            end_range: End of the number range (inclusive).

        Returns:
            Pool ID.
        """
        existing = self.get_pool_by_name("CoreNumberPool", name)
        if existing:
            logger.info("Number pool '%s' already exists: %s", name, existing[:8])
            return existing

        data: dict[str, Any] = {
            "name": {"value": name},
            "description": {"value": description},
            "start_range": {"value": start_range},
            "end_range": {"value": end_range},
        }
        result = self._graphql(MUTATION_CREATE_NUMBER_POOL, variables={"data": data})
        create_result = result.get("CoreNumberPoolCreate", {})
        if not create_result.get("ok"):
            raise RuntimeError(f"Failed to create number pool '{name}': {result}")

        pool_id: str = create_result["object"]["id"]
        logger.info("Created number pool '%s': %s", name, pool_id[:8])
        return pool_id

    # -- resource allocation --

    def allocate_prefix(
        self,
        pool_id: str,
        prefix_length: int | None = None,
        identifier: str | None = None,
    ) -> AllocationResult:
        """Allocate an IP prefix from a prefix pool.

        Args:
            pool_id: ID of the CoreIPPrefixPool.
            prefix_length: Override default prefix length for this allocation.
            identifier: Optional label for the allocation (e.g. "spine01-leaf01").

        Returns:
            AllocationResult with the allocated prefix.

        Raises:
            PoolExhaustedError: If the pool has no available prefixes.
        """
        variables: dict[str, Any] = {"pool_id": pool_id}
        if identifier:
            variables["identifier"] = identifier
        if prefix_length is not None:
            variables["prefix_length"] = prefix_length

        result = self._graphql(MUTATION_ALLOCATE_PREFIX, variables=variables)
        alloc = result.get("IPPrefixPoolGetResource", {})
        if not alloc.get("ok"):
            raise PoolExhaustedError(pool_id)

        node = alloc["node"]
        return AllocationResult(
            id=node["id"],
            value=node["prefix"]["value"],
            pool_id=pool_id,
        )

    def allocate_ip_address(
        self,
        pool_id: str,
        identifier: str | None = None,
    ) -> AllocationResult:
        """Allocate an IP address from an address pool.

        Args:
            pool_id: ID of the CoreIPAddressPool.
            identifier: Optional label for the allocation.

        Returns:
            AllocationResult with the allocated IP address.

        Raises:
            PoolExhaustedError: If the pool has no available addresses.
        """
        variables: dict[str, Any] = {"pool_id": pool_id}
        if identifier:
            variables["identifier"] = identifier

        result = self._graphql(MUTATION_ALLOCATE_IP_ADDRESS, variables=variables)
        alloc = result.get("IPAddressPoolGetResource", {})
        if not alloc.get("ok"):
            raise PoolExhaustedError(pool_id)

        node = alloc["node"]
        return AllocationResult(
            id=node["id"],
            value=node["address"]["value"],
            pool_id=pool_id,
        )

    def allocate_number(
        self,
        pool_id: str,
        identifier: str | None = None,
    ) -> AllocationResult:
        """Allocate a number from a number pool.

        Args:
            pool_id: ID of the CoreNumberPool.
            identifier: Optional label for the allocation.

        Returns:
            AllocationResult with the allocated number.

        Raises:
            PoolExhaustedError: If the pool has no available numbers.
        """
        variables: dict[str, Any] = {"pool_id": pool_id}
        if identifier:
            variables["identifier"] = identifier

        result = self._graphql(MUTATION_ALLOCATE_NUMBER, variables=variables)
        alloc = result.get("NumberPoolGetResource", {})
        if not alloc.get("ok"):
            raise PoolExhaustedError(pool_id)

        node = alloc["node"]
        return AllocationResult(
            id=node["id"],
            value=node["value"],
            pool_id=pool_id,
        )

    # -- high-level provisioning --

    def provision_device(
        self,
        device_name: str,
        role: str,
        peer_devices: list[str],
        asn_pool_name: str = "asn-pool",
        loopback_pool_name: str = "loopback-addresses",
        fabric_pool_name: str = "fabric-underlay",
    ) -> ProvisioningResult:
        """Allocate all resources needed for a new device.

        Allocates from named pools:
        1. ASN from the number pool
        2. Loopback /32 IP from the address pool
        3. One fabric /31 prefix per peer device from the prefix pool

        Args:
            device_name: Name of the device being provisioned.
            role: Device role (spine, leaf, etc.).
            peer_devices: List of peer device names for fabric links.
            asn_pool_name: Name of the ASN number pool.
            loopback_pool_name: Name of the loopback address pool.
            fabric_pool_name: Name of the fabric prefix pool.

        Returns:
            ProvisioningResult with all allocated resources.

        Raises:
            PoolNotFoundError: If a required pool doesn't exist.
            PoolExhaustedError: If any pool runs out of resources.
        """
        # Resolve pool IDs
        asn_pool_id = self.get_pool_by_name("CoreNumberPool", asn_pool_name)
        if not asn_pool_id:
            raise PoolNotFoundError("CoreNumberPool", asn_pool_name)

        loopback_pool_id = self.get_pool_by_name("CoreIPAddressPool", loopback_pool_name)
        if not loopback_pool_id:
            raise PoolNotFoundError("CoreIPAddressPool", loopback_pool_name)

        fabric_pool_id = self.get_pool_by_name("CoreIPPrefixPool", fabric_pool_name)
        if not fabric_pool_id:
            raise PoolNotFoundError("CoreIPPrefixPool", fabric_pool_name)

        # 1. Allocate ASN
        asn_result = self.allocate_number(asn_pool_id, identifier=device_name)
        logger.info("Allocated ASN %s for %s", asn_result.value, device_name)

        # 2. Allocate loopback IP
        loopback_result = self.allocate_ip_address(loopback_pool_id, identifier=f"{device_name}-loopback")
        logger.info("Allocated loopback %s for %s", loopback_result.value, device_name)

        # 3. Allocate fabric /31 per peer
        fabric_links: list[FabricLinkAllocation] = []
        for peer in peer_devices:
            link_id = f"{device_name}-{peer}"
            prefix_result = self.allocate_prefix(fabric_pool_id, prefix_length=31, identifier=link_id)
            prefix = prefix_result.value

            # Derive local/remote IPs from the /31 prefix
            # For a /31 like 10.0.0.8/31: first IP = 10.0.0.8, second = 10.0.0.9
            network = ipaddress.ip_network(prefix, strict=False)
            hosts = list(network.hosts()) if network.prefixlen < 31 else list(network)
            local_ip = f"{hosts[0]}/{network.prefixlen}"
            remote_ip = f"{hosts[1]}/{network.prefixlen}"

            fabric_links.append(
                FabricLinkAllocation(
                    prefix=prefix,
                    local_ip=local_ip,
                    remote_ip=remote_ip,
                    peer_device=peer,
                )
            )
            logger.info("Allocated fabric %s for %s <-> %s", prefix, device_name, peer)

        return ProvisioningResult(
            device_name=device_name,
            role=role,
            asn=int(asn_result.value),
            loopback_ip=str(loopback_result.value),
            fabric_links=fabric_links,
        )

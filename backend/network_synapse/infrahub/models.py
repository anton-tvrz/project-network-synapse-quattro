"""Pydantic models for Infrahub data and SR Linux template variables.

Two model layers:
  1. Data models — parsed from Infrahub GraphQL responses (DeviceData, InterfaceData, BGPSessionData)
  2. Template models — exact variable shapes for Jinja2 templates (BGPTemplateVars, InterfacesTemplateVars)

The DeviceConfig model bridges the two layers with transformer methods.
"""

from __future__ import annotations

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Data models — parsed from Infrahub GraphQL responses
# ---------------------------------------------------------------------------


class DeviceData(BaseModel):
    """Device data extracted from Infrahub DcimDevice query."""

    id: str = ""
    name: str
    description: str = ""
    management_ip: str = ""
    lab_node_name: str = ""
    role: str = ""
    status: str = "active"
    asn: int
    router_id: str = ""  # Derived from loopback0 IP (bare IP, no CIDR)


class InterfaceData(BaseModel):
    """Interface data extracted from Infrahub InterfacePhysical query."""

    name: str
    description: str = ""
    mtu: int = 9214
    role: str = ""
    ip_address: str | None = None  # CIDR notation (e.g. "10.0.0.0/31")
    enabled: bool = True


class BGPSessionData(BaseModel):
    """BGP session data extracted from Infrahub RoutingBGPSession query."""

    description: str = ""
    session_type: str = "EXTERNAL"
    role: str = "backbone"
    local_asn: int
    remote_asn: int
    local_ip: str  # CIDR notation from Infrahub
    remote_ip: str  # CIDR notation from Infrahub
    peer_group: str = "underlay"


# ---------------------------------------------------------------------------
# Template variable models — exact shapes for Jinja2 templates
# ---------------------------------------------------------------------------


class BGPTemplateSession(BaseModel):
    """Single BGP neighbor entry for srlinux_bgp.j2 template."""

    remote_ip: str  # Bare IP — no CIDR (SR Linux peer-address)
    remote_asn: int
    group: str = "underlay"
    description: str = ""


class BGPTemplateVars(BaseModel):
    """Variables for the srlinux_bgp.j2 template."""

    network_instance: str = "default"
    local_asn: int
    router_id: str  # Bare IP — no CIDR
    group_name: str = "underlay"
    export_policy: str = "export-all"
    import_policy: str = "import-all"
    bgp_sessions: list[BGPTemplateSession]


class InterfaceTemplateEntry(BaseModel):
    """Single interface entry for srlinux_interfaces.j2 template."""

    name: str
    description: str = ""
    enabled: bool = True
    mtu: int = 9214
    subinterface_index: int = 0
    ip_address: str | None = None  # Full CIDR notation (SR Linux ip-prefix)


class InterfacesTemplateVars(BaseModel):
    """Variables for the srlinux_interfaces.j2 template."""

    interfaces: list[InterfaceTemplateEntry]


# ---------------------------------------------------------------------------
# Resource manager models — pool definitions and allocation results
# ---------------------------------------------------------------------------


class ResourcePoolData(BaseModel):
    """Base data for a resource pool."""

    id: str = ""
    name: str
    description: str = ""


class IPPrefixPoolData(ResourcePoolData):
    """IP prefix pool data."""

    default_prefix_length: int


class IPAddressPoolData(ResourcePoolData):
    """IP address pool data."""

    default_prefix_length: int = 32


class NumberPoolData(ResourcePoolData):
    """Number pool data."""

    start_range: int
    end_range: int


class AllocationResult(BaseModel):
    """Result of a resource allocation from a pool."""

    id: str
    value: str | int
    pool_id: str


class FabricLinkAllocation(BaseModel):
    """Allocated fabric link between two devices."""

    prefix: str  # e.g. "10.0.0.8/31"
    local_ip: str  # e.g. "10.0.0.8/31"
    remote_ip: str  # e.g. "10.0.0.9/31"
    peer_device: str


class ProvisioningResult(BaseModel):
    """Result of provisioning all resources for a new device."""

    device_name: str
    role: str
    asn: int
    loopback_ip: str  # e.g. "10.1.0.4/32"
    fabric_links: list[FabricLinkAllocation]


# ---------------------------------------------------------------------------
# Aggregate model — bridges data layer and template layer
# ---------------------------------------------------------------------------


def _strip_cidr(ip: str) -> str:
    """Strip prefix length from an IP address: '10.0.0.1/31' -> '10.0.0.1'."""
    return ip.split("/", maxsplit=1)[0] if "/" in ip else ip


class DeviceConfig(BaseModel):
    """Complete device configuration from Infrahub.

    Aggregates device metadata, interfaces, and BGP sessions.
    Provides transformer methods to produce template-ready variable dicts.
    """

    device: DeviceData
    interfaces: list[InterfaceData]
    bgp_sessions: list[BGPSessionData]

    def to_bgp_template_vars(self) -> BGPTemplateVars:
        """Transform to BGP template variables.

        - Strips CIDR from remote_ip (SR Linux peer-address is bare IP)
        - Uses device.router_id (already bare IP, derived from loopback0)
        """
        sessions = [
            BGPTemplateSession(
                remote_ip=_strip_cidr(s.remote_ip),
                remote_asn=s.remote_asn,
                group=s.peer_group,
                description=s.description,
            )
            for s in self.bgp_sessions
        ]
        return BGPTemplateVars(
            local_asn=self.device.asn,
            router_id=self.device.router_id,
            bgp_sessions=sessions,
        )

    def to_interface_template_vars(self) -> InterfacesTemplateVars:
        """Transform to interface template variables.

        - Keeps CIDR on ip_address (SR Linux ip-prefix expects CIDR)
        - Filters to fabric + loopback interfaces (skip management)
        """
        entries = [
            InterfaceTemplateEntry(
                name=iface.name,
                description=iface.description,
                enabled=iface.enabled,
                mtu=iface.mtu,
                ip_address=iface.ip_address,
            )
            for iface in self.interfaces
            if iface.role in ("fabric", "loopback")
        ]
        return InterfacesTemplateVars(interfaces=entries)

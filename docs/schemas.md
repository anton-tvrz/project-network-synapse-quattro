# Infrahub Schema Architecture

This document describes the Infrahub schema design for the Synapse project.

## Overview

The schema is built in layers:

1. **Base schemas** — provided by the [OpsMill schema-library](https://github.com/opsmill/schema-library) (`library/schema-library/base/`)
2. **Community extensions** — reusable extensions from the schema-library (`library/schema-library/extensions/`)
3. **Custom extensions** — project-specific attributes and relationships (`infrahub/schemas/`)

## Schema Load Order

Schemas must be loaded in dependency order. The loader script (`infrahub/schemas/load_schemas.py`) handles this automatically.

```
1. library/schema-library/extensions/vrf/vrf.yml
   -> IpamVRF, IpamRouteTarget
   -> Extends IpamIPAddress and IpamPrefix with VRF relationship

2. library/schema-library/extensions/routing/routing.yml
   -> RoutingProtocol (generic)
   -> Depends on: DcimDevice, IpamVRF

3. library/schema-library/extensions/routing_bgp/bgp.yml
   -> RoutingAutonomousSystem, RoutingBGPPeerGroup, RoutingBGPSession
   -> Extends DcimGenericDevice with ASN relationship
   -> Extends OrganizationGeneric with ASN relationship
   -> Depends on: RoutingProtocol, DcimDevice, IpamIPAddress

4. infrahub/schemas/network_device.yml
   -> Extends DcimDevice with: management_ip, lab_node_name, asn
   -> Depends on: RoutingAutonomousSystem

5. infrahub/schemas/network_interface.yml
   -> Extends InterfacePhysical with: role (dropdown)
```

## Loading Schemas

```bash
# From your laptop (schemas are sent to VM via API)
cd ~/PYPROJECTS/project-network-synapse-3
python infrahub/schemas/load_schemas.py --url http://localhost:8000

# Dry run (parse only, no API calls)
python infrahub/schemas/load_schemas.py --dry-run

# With explicit token
python infrahub/schemas/load_schemas.py --url http://localhost:8000 --token <your-token>
```

## Base Schema Nodes (Pre-loaded)

These nodes are provided by the schema-library base and are always available:

| Node | Namespace | Key Attributes |
|------|-----------|----------------|
| DcimDevice | Dcim | name, status, role, description, os_version, serial |
| DcimDeviceType | Dcim | name, part_number, height, full_depth |
| DcimPlatform | Dcim | name, nornir_platform, napalm_driver, netmiko_device_type |
| InterfacePhysical | Interface | name, status, mtu, mac_address, l2_mode |
| InterfaceVirtual | Interface | name, status, mtu |
| IpamIPAddress | Ipam | address, description, fqdn |
| IpamPrefix | Ipam | prefix, description |
| IpamNamespace | Ipam | name, description |
| LocationSite | Location | name, shortname, description |
| LocationRack | Location | name, height |
| OrganizationManufacturer | Organization | name, description |
| OrganizationProvider | Organization | name, description |
| BuiltinTag | Builtin | name, description |

## Extension: VRF (`vrf.yml`)

| Node | Key Attributes | Key Relationships |
|------|----------------|-------------------|
| IpamVRF | name, vrf_rd, description | namespace (IpamNamespace), import_rt, export_rt |
| IpamRouteTarget | name, description | vrf (IpamVRF) |

Also extends:
- `IpamPrefix` with `vrf` relationship
- `IpamIPAddress` with `vrf` relationship

## Extension: Routing Base (`routing.yml`)

| Generic | Key Attributes | Key Relationships |
|---------|----------------|-------------------|
| RoutingProtocol | description, status (active/disabled/deleted) | device (DcimDevice), vrf (IpamVRF) |

## Extension: Routing BGP (`bgp.yml`)

| Node | Key Attributes | Key Relationships |
|------|----------------|-------------------|
| RoutingAutonomousSystem | name, asn (BigInt), description | organization, location, devices |
| RoutingBGPPeerGroup | name, import_policies, export_policies, local_pref | local_as, remote_as |
| RoutingBGPSession | description, session_type (EXTERNAL/INTERNAL), role, status | device, local_as, remote_as, local_ip, remote_ip, peer_group, peer_session, vrf |

Inherits from `RoutingProtocol`: device and vrf relationships.

Also extends:
- `DcimGenericDevice` with `asn` relationship
- `OrganizationGeneric` with `asn` relationship

## Custom Extension: Network Device (`network_device.yml`)

Adds project-specific attributes to `DcimDevice`:

| Attribute | Kind | Description |
|-----------|------|-------------|
| management_ip | IPHost | Out-of-band management IP address |
| lab_node_name | Text | Containerlab container name (e.g., `clab-spine-leaf-lab-spine01`) |

Also adds:
- `asn` relationship to `RoutingAutonomousSystem` (overrides the generic one with custom ordering)

## Custom Extension: Network Interface (`network_interface.yml`)

Adds a `role` dropdown to `InterfacePhysical`:

| Choice | Label | Description |
|--------|-------|-------------|
| fabric | Fabric | Inter-switch fabric link (spine-leaf) |
| loopback | Loopback | Loopback interface for router-id and peering |
| management | Management | Out-of-band management interface |
| access | Access | Host-facing access port |

## Schema Diagram

```
OrganizationManufacturer ──┐
                           │ manufacturer
                     ┌─────┴──────┐
                     │ DcimPlatform│
                     └─────┬──────┘
                           │ platform
┌──────────────┐     ┌─────┴──────┐     ┌────────────────────┐
│ LocationSite │────▶│ DcimDevice  │◀────│ RoutingAutonomous  │
└──────────────┘     │             │     │ System (ASN)       │
   location          │ + mgmt_ip   │     └────────────────────┘
                     │ + lab_node  │            ▲
                     └──────┬──────┘            │ local_as / remote_as
                            │ device            │
                     ┌──────┴──────────┐  ┌─────┴──────────┐
                     │InterfacePhysical│  │RoutingBGPSession│
                     │ + role          │  │ + session_type  │
                     └────────┬────────┘  │ + local/remote  │
                              │           └─────┬───────────┘
                       ┌──────┴──────┐          │
                       │IpamIPAddress │◀─────────┘
                       │ + address    │  local_ip / remote_ip
                       └─────────────┘
```

## Resource Pools

Infrahub's built-in resource pool system enables dynamic IP and ASN allocation. See [resource-manager.md](resource-manager.md) for full documentation.

### Pool Types

| Pool Type | Infrahub Kind | Allocates |
|-----------|---------------|-----------|
| IP Prefix Pool | `CoreIPPrefixPool` | IP prefixes (e.g., /31 for fabric links) |
| IP Address Pool | `CoreIPAddressPool` | Individual IP addresses (e.g., /32 loopbacks) |
| Number Pool | `CoreNumberPool` | Integers from a range (e.g., ASNs) |

### Project Pools

| Pool Name | Type | Source | Default Allocation |
|-----------|------|--------|--------------------|
| `fabric-underlay` | IP Prefix | `10.0.0.0/16` | /31 |
| `loopback-pool` | IP Prefix | `10.1.0.0/24` | /32 |
| `loopback-addresses` | IP Address | loopback-pool | /32 |
| `asn-pool` | Number | 65000–65534 | Single integer |

Pools are created via `populate_sot.py --with-pools`. See [seed-data.md](seed-data.md) for details.

## GraphQL Query Examples

### Query all devices with their ASN and interfaces

```graphql
{
  DcimDevice {
    edges {
      node {
        display_label
        name { value }
        role { value }
        management_ip { value }
        lab_node_name { value }
        asn {
          node {
            asn { value }
            name { value }
          }
        }
        interfaces {
          edges {
            node {
              name { value }
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
    }
  }
}
```

### Query all BGP sessions

```graphql
{
  RoutingBGPSession {
    edges {
      node {
        display_label
        description { value }
        session_type { value }
        status { value }
        device {
          node { display_label }
        }
        local_as {
          node { asn { value } }
        }
        remote_as {
          node { asn { value } }
        }
        local_ip {
          node { address { value } }
        }
        remote_ip {
          node { address { value } }
        }
      }
    }
  }
}
```

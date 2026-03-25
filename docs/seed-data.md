# Seed Data Reference

This document describes the seed data populated into Infrahub for the Synapse spine-leaf lab.

Source file: `infrahub/data/seed_data.yml`
Loader script: `infrahub/data/populate_sot.py`

## Running the Seed Script

```bash
# Load seed data into Infrahub
python infrahub/data/populate_sot.py \
  --url http://localhost:8000 \
  --seed-file infrahub/data/seed_data.yml

# Dry run (parse only)
python infrahub/data/populate_sot.py --dry-run

# With resource pools (dynamic IP/ASN allocation)
python infrahub/data/populate_sot.py \
  --url http://localhost:8000 \
  --with-pools \
  --pool-file infrahub/data/pool_definitions.yml
```

The script is idempotent — it checks for existing objects before creating and can be safely re-run.

### `--with-pools` Flag

When `--with-pools` is specified, the seed script additionally:

1. Creates IP prefix supernets (e.g., `10.0.0.0/16`, `10.1.0.0/24`)
2. Creates resource pools referencing those prefixes
3. Pools can then be used for dynamic allocation via the Resource Manager

See [resource-manager.md](resource-manager.md) for details on pool allocation.

## Organization & Location

| Object | Type | Name |
|--------|------|------|
| Manufacturer | OrganizationManufacturer | Nokia |
| Location | LocationSite | Local Lab (`local-lab`) |
| Platform | DcimPlatform | Nokia SR Linux |

### Platform Driver Mappings

| Framework | Driver / Platform |
|-----------|-------------------|
| Nornir | `srlinux` |
| NAPALM | `srl` |
| Netmiko | `nokia_srl` |
| Ansible | `nokia.srlinux.srlinux` |
| Containerlab | `nokia_srlinux` |

## Device Types

| Name | Part Number | Description |
|------|-------------|-------------|
| 7220 IXR-D3 | 7220-IXR-D3 | Spine/Aggregation switch |
| 7220 IXR-D2 | 7220-IXR-D2 | Leaf/Top-of-Rack switch |

## Devices

| Device | Role | Type | Management IP | Containerlab Name | ASN |
|--------|------|------|---------------|-------------------|-----|
| spine01 | spine | 7220 IXR-D3 | 172.20.20.3/24 | clab-spine-leaf-lab-spine01 | 65000 |
| leaf01 | leaf | 7220 IXR-D2 | 172.20.20.2/24 | clab-spine-leaf-lab-leaf01 | 65001 |
| leaf02 | leaf | 7220 IXR-D2 | 172.20.20.4/24 | clab-spine-leaf-lab-leaf02 | 65002 |

> **Note:** The Containerlab topology explicitly includes additional Linux testing nodes (`client1`, `client2`, `firewall`) that are excluded from the Infrahub Source of Truth as they are purely logical end-hosts for verifying data plane conductivity.

## Autonomous Systems

| ASN | Name | Description |
|-----|------|-------------|
| 65000 | Spine AS | Spine tier autonomous system |
| 65001 | Leaf01 AS | Leaf01 autonomous system |
| 65002 | Leaf02 AS | Leaf02 autonomous system |

## IP Addressing Plan

### Fabric Underlay (/31 Point-to-Point)

| Link | Spine IP | Leaf IP | Spine Interface | Leaf Interface |
|------|----------|---------|-----------------|----------------|
| spine01-leaf01 (1) | 10.0.0.0/31 | 10.0.0.1/31 | ethernet-1/1 | ethernet-1/49 |
| spine01-leaf02 (1) | 10.0.0.2/31 | 10.0.0.3/31 | ethernet-1/2 | ethernet-1/49 |
| spine01-leaf01 (2) | 10.0.0.4/31 | 10.0.0.5/31 | ethernet-1/3 | ethernet-1/50 |
| spine01-leaf02 (2) | 10.0.0.6/31 | 10.0.0.7/31 | ethernet-1/4 | ethernet-1/50 |

### Loopbacks (/32 Router ID)

| Device | Loopback IP | Interface |
|--------|-------------|-----------|
| spine01 | 10.1.0.1/32 | loopback0 |
| leaf01 | 10.1.0.2/32 | loopback0 |
| leaf02 | 10.1.0.3/32 | loopback0 |

### Supernets

| Prefix | Description |
|--------|-------------|
| 172.20.20.0/24 | Containerlab management network |
| 10.0.0.0/16 | Fabric underlay supernet |
| 10.1.0.0/24 | Loopback supernet |

## Interfaces

### spine01

| Interface | Role | Description | IP Address | MTU |
|-----------|------|-------------|------------|-----|
| ethernet-1/1 | fabric | to leaf01:ethernet-1/49 | 10.0.0.0/31 | 9214 |
| ethernet-1/2 | fabric | to leaf02:ethernet-1/49 | 10.0.0.2/31 | 9214 |
| ethernet-1/3 | fabric | to leaf01:ethernet-1/50 | 10.0.0.4/31 | 9214 |
| ethernet-1/4 | fabric | to leaf02:ethernet-1/50 | 10.0.0.6/31 | 9214 |
| loopback0 | loopback | Router ID - spine01 | 10.1.0.1/32 | - |

### leaf01

| Interface | Role | Description | IP Address | MTU |
|-----------|------|-------------|------------|-----|
| ethernet-1/49 | fabric | to spine01:ethernet-1/1 | 10.0.0.1/31 | 9214 |
| ethernet-1/50 | fabric | to spine01:ethernet-1/3 | 10.0.0.5/31 | 9214 |
| loopback0 | loopback | Router ID - leaf01 | 10.1.0.2/32 | - |

### leaf02

| Interface | Role | Description | IP Address | MTU |
|-----------|------|-------------|------------|-----|
| ethernet-1/49 | fabric | to spine01:ethernet-1/2 | 10.0.0.3/31 | 9214 |
| ethernet-1/50 | fabric | to spine01:ethernet-1/4 | 10.0.0.7/31 | 9214 |
| loopback0 | loopback | Router ID - leaf02 | 10.1.0.3/32 | - |

## BGP Sessions (eBGP Underlay)

All sessions are eBGP (`EXTERNAL`) with role `backbone` in the default VRF.

| Description | Local Device | Remote Device | Local AS | Remote AS | Local IP | Remote IP |
|-------------|-------------|---------------|----------|-----------|----------|-----------|
| spine01:e1-1 <-> leaf01:e1-49 | spine01 | leaf01 | 65000 | 65001 | 10.0.0.0/31 | 10.0.0.1/31 |
| spine01:e1-3 <-> leaf01:e1-50 | spine01 | leaf01 | 65000 | 65001 | 10.0.0.4/31 | 10.0.0.5/31 |
| spine01:e1-2 <-> leaf02:e1-49 | spine01 | leaf02 | 65000 | 65002 | 10.0.0.2/31 | 10.0.0.3/31 |
| spine01:e1-4 <-> leaf02:e1-50 | spine01 | leaf02 | 65000 | 65002 | 10.0.0.6/31 | 10.0.0.7/31 |

## Object Creation Order

The `populate_sot.py` script creates objects in strict dependency order:

1. OrganizationManufacturer (Nokia)
2. LocationSite (Local Lab)
3. DcimPlatform (Nokia SR Linux) — requires manufacturer
4. DcimDeviceType (IXR-D3, IXR-D2) — requires manufacturer, platform
5. RoutingAutonomousSystem (AS65000-65002) — requires organization
6. IpamNamespace (default)
7. IpamVRF (default) — requires namespace
8. DcimDevice (spine01, leaf01, leaf02) — requires location, platform, device_type, asn
9. IpamPrefix (supernets) — requires namespace *(only with `--with-pools`)*
10. **Resource Pools** (prefix, address, number pools) — requires prefixes *(only with `--with-pools`)*
11. IpamIPAddress (all /31 and /32) — requires namespace
12. InterfacePhysical (all interfaces) — requires device, ip_addresses
13. RoutingBGPSession (all 4 sessions) — requires device, local_as, remote_as, local_ip, remote_ip, vrf

### Pool Definitions Reference

When using `--with-pools`, pool configuration is read from `pool_definitions.yml`:

| Pool Name | Type | Description | Default Size |
|-----------|------|-------------|--------------|
| `fabric-underlay` | `CoreIPPrefixPool` | Fabric /31 point-to-point links | /31 |
| `loopback-pool` | `CoreIPPrefixPool` | Loopback prefix allocation | /32 |
| `loopback-addresses` | `CoreIPAddressPool` | Individual loopback IPs | /32 |
| `asn-pool` | `CoreNumberPool` | ASN allocation (65000–65534) | — |

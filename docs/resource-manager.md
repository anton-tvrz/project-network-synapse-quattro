# Resource Manager

The Infrahub Resource Manager provides dynamic IP and ASN allocation using Infrahub's built-in resource pool system, replacing static IP/ASN assignment in seed data.

## Concepts

### Resource Pools

Infrahub provides three built-in pool types:

| Pool Type | Allocates | Use Case |
|-----------|-----------|----------|
| `CoreIPPrefixPool` | IP prefixes (e.g., /31) | Fabric point-to-point links |
| `CoreIPAddressPool` | Individual IP addresses (e.g., /32) | Loopback addresses |
| `CoreNumberPool` | Integer values from a range | ASN allocation |

### Pool Definitions

Pool configuration is defined in `backend/network_synapse/data/pool_definitions.yml`:

| Pool Name | Type | Description |
|-----------|------|-------------|
| `fabric-underlay` | IP Prefix | /31 allocations from `10.0.0.0/16` |
| `loopback-pool` | IP Prefix | /32 allocations from `10.1.0.0/24` |
| `loopback-addresses` | IP Address | Individual loopback IPs from loopback-pool |
| `asn-pool` | Number | ASN range 65000–65534 |

## Usage

### Creating Pools (Seed Pipeline)

Pools are created during data seeding with the `--with-pools` flag:

```bash
uv run python backend/network_synapse/data/populate_sot.py \
  --url http://localhost:8000 \
  --with-pools
```

This creates IP prefix supernets first, then resource pools referencing those prefixes.

### Programmatic Usage

```python
from network_synapse.infrahub.resource_manager import InfrahubResourceManager

with InfrahubResourceManager(url="http://localhost:8000") as mgr:
    # Create a pool
    pool_id = mgr.create_ip_prefix_pool(
        "fabric-underlay", "Fabric /31s", 31, [prefix_id]
    )

    # Allocate from pool
    result = mgr.allocate_prefix(pool_id, prefix_length=31, identifier="spine01-leaf01")
    print(result.value)  # "10.0.0.0/31"
```

### Device Provisioning

The `provision_device()` method orchestrates full resource allocation:

```python
result = mgr.provision_device("leaf03", "leaf", peer_devices=["spine01"])
# result.asn          -> 65003
# result.loopback_ip  -> "10.1.0.4/32"
# result.fabric_links -> [FabricLinkAllocation(prefix="10.0.0.8/31", ...)]
```

### Temporal Integration

The `allocate_device_resources` Temporal activity wraps `provision_device()` for use in durable workflows.

## GraphQL Examples

### Allocate a prefix

```graphql
mutation {
  IPPrefixPoolGetResource(
    data: { id: "pool-id", identifier: "spine01-leaf01", prefix_length: 31 }
  ) {
    ok
    node { id prefix { value } }
  }
}
```

### Look up a pool by name

```graphql
{
  CoreIPPrefixPool(name__value: "fabric-underlay") {
    edges { node { id } }
  }
}
```

## Key Files

| File | Purpose |
|------|---------|
| `backend/network_synapse/infrahub/resource_manager.py` | Resource manager client |
| `backend/network_synapse/infrahub/models.py` | Pydantic models (AllocationResult, ProvisioningResult) |
| `backend/network_synapse/data/pool_definitions.yml` | Pool configuration |
| `backend/network_synapse/data/populate_sot.py` | Pool creation in seed pipeline |
| `workers/synapse_workers/activities/infrahub_activities.py` | Temporal activity |

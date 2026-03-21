# Transforms and Checks

Infrahub transforms and checks move config generation and data validation server-side, running within the Infrahub Git integration.

## Overview

| Component | Purpose | Base Class |
|-----------|---------|------------|
| **Transforms** | Generate device configs from GraphQL query data | `InfrahubTransform` |
| **Checks** | Validate data consistency and flag errors | `InfrahubCheck` |

Both are registered in `.infrahub.yml` at the project root and discovered by Infrahub's Git sync.

## Transforms

### Available Transforms

| Transform | Output | Replaces |
|-----------|--------|----------|
| `srlinux_bgp_config` | SR Linux BGP JSON | `templates/srlinux_bgp.j2` |
| `srlinux_interface_config` | SR Linux Interface JSON | `templates/srlinux_interfaces.j2` |

### Using Transforms

**Via `generate_configs.py` (gradual migration):**

```bash
# Default: local Jinja2 rendering (unchanged)
uv run python backend/network_synapse/scripts/generate_configs.py spine01

# New: server-side Infrahub transforms
uv run python backend/network_synapse/scripts/generate_configs.py spine01 --use-transforms
```

**Via Python API:**

```python
from network_synapse.infrahub.client import InfrahubConfigClient

client = InfrahubConfigClient(url="http://localhost:8000")
result = client.execute_transform("srlinux_bgp_config", {"hostname": "spine01"})
```

### Transform Details

**BGP Transform** (`srlinux_bgp_transform.py`):
- Queries device ASN, BGP sessions, and loopback interface
- Strips CIDR from peer addresses (e.g., `10.0.0.1/31` -> `10.0.0.1`)
- Derives `router-id` from loopback IP
- Produces identical JSON to the Jinja2 template

**Interface Transform** (`srlinux_interface_transform.py`):
- Queries all device interfaces with IP addresses
- Filters to `fabric` and `loopback` roles only (excludes `management`)
- Preserves CIDR notation on IP prefixes

## Checks

### Available Checks

| Check | Validates |
|-------|-----------|
| `validate_bgp_sessions` | ASN values > 0, IP addresses present, EXTERNAL sessions have different ASNs |
| `validate_ip_uniqueness` | No duplicate IPs within the same namespace |
| `validate_interface_consistency` | Fabric interfaces have IPs and descriptions, loopbacks have IPs |

### How Checks Work

Checks run automatically via Infrahub's proposed change validation or can be triggered manually. Each check:

1. Queries data via its associated GraphQL query
2. Validates the data using `self.log_error()` to flag issues
3. Any `log_error()` call causes the check to fail

## `.infrahub.yml` Reference

The manifest file declares all transforms, checks, and queries:

```yaml
python_transforms:
  - name: "srlinux_bgp_config"
    file_path: "backend/network_synapse/transforms/srlinux_bgp_transform.py"
    class_name: "SRLinuxBGPTransform"

check_definitions:
  - name: "validate_bgp_sessions"
    file_path: "backend/network_synapse/checks/bgp_session_check.py"
    class_name: "BGPSessionCheck"

queries:
  - name: "device_bgp_config"
    file_path: "backend/network_synapse/queries/device_bgp_config.gql"
```

## Key Files

| File | Purpose |
|------|---------|
| `.infrahub.yml` | Repository manifest (transforms, checks, queries) |
| `backend/network_synapse/transforms/` | Transform implementations |
| `backend/network_synapse/checks/` | Check implementations |
| `backend/network_synapse/queries/` | GraphQL query files (.gql) |
| `backend/network_synapse/infrahub/client.py` | `execute_transform()` method |
| `backend/network_synapse/scripts/generate_configs.py` | `--use-transforms` flag |

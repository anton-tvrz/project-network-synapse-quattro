# Backend Architecture

## Overview

The backend package (`network_synapse`) handles all interaction with Infrahub (Source of Truth), configuration generation, and network device management.

## Components

### Data Layer (`data/`)

- **`populate_sot.py`** — Seeds Infrahub with the full spine-leaf topology via GraphQL mutations. Supports idempotent upserts (get-or-create pattern). Dependency-ordered: manufacturer -> location -> platform -> device types -> ASNs -> namespace -> VRFs -> devices -> IPs -> interfaces -> BGP sessions.
- **`seed_data.yml`** — YAML inventory defining the entire lab topology: 3 Nokia SR Linux devices, 11 interfaces, 4 eBGP sessions, IP addressing scheme.

### Schema Layer (`schemas/`)

- **`load_schemas.py`** — Loads Infrahub schema extensions in dependency order via the `/api/schema/load` REST endpoint. Loads: VRF -> routing base -> routing BGP -> device extensions -> interface extensions.
- **Schema YAML files** — Extend Infrahub's built-in types with project-specific attributes (e.g., `management_ip`, `lab_node_name`, `asn` on DcimDevice).

### Infrahub Client (`infrahub/`)

- **`client.py`** — `InfrahubConfigClient` for querying device configs, listing devices, and executing transforms via GraphQL. Uses httpx with lazy authentication.
- **`resource_manager.py`** — `InfrahubResourceManager` for dynamic IP and ASN allocation via Infrahub's built-in resource pools (CoreIPPrefixPool, CoreIPAddressPool, CoreNumberPool). Provides pool creation, allocation, and high-level device provisioning.
- **`models.py`** — Pydantic models for device configs, template vars, pool data, and allocation results.

### Transforms (`transforms/`)

Server-side config generation using Infrahub's transform system:

- **`srlinux_bgp_transform.py`** — Generates SR Linux BGP JSON from GraphQL data (replaces `srlinux_bgp.j2`)
- **`srlinux_interface_transform.py`** — Generates SR Linux interface JSON (replaces `srlinux_interfaces.j2`)

Both extend `infrahub_sdk.transforms.InfrahubTransform`. Registered in `.infrahub.yml`.

### Checks (`checks/`)

Server-side data validation using Infrahub's check system:

- **`bgp_session_check.py`** — Validates ASN values, IP presence, session type consistency
- **`ip_uniqueness_check.py`** — Detects duplicate IPs within the same namespace
- **`interface_consistency_check.py`** — Validates fabric interfaces have IPs and descriptions

All extend `infrahub_sdk.checks.InfrahubCheck`. Registered in `.infrahub.yml`.

### GraphQL Queries (`queries/`)

- **`device_bgp_config.gql`** — Device + BGP sessions (BGP transform)
- **`device_interface_config.gql`** — Device + interfaces (interface transform)
- **`all_bgp_sessions.gql`** — All BGP sessions (BGP check)
- **`all_ip_addresses.gql`** — All IP addresses (IP uniqueness check)
- **`all_device_interfaces.gql`** — All interfaces (interface check)

### Scripts (`scripts/`)

- **`generate_configs.py`** — Renders Jinja2 templates into Nokia SR Linux JSON configurations suitable for gNMI deployment. Uses `FileSystemLoader` pointing to `templates/`.
- **`deploy_configs.py`** — (Stub) Will push generated configs to devices via pygnmi/gNMI.
- **`validate_configs.py`** — (Stub) Will validate post-deployment state via gNMI GET.

### Templates (`templates/`)

- **`srlinux_bgp.j2`** — Renders BGP configuration in SR Linux JSON-RPC/gNMI format.
- **`srlinux_interfaces.j2`** — Renders interface configuration in SR Linux JSON format.

## Testing Philosophy

This project follows strict TDD (see [ADR-0004](../../adr/0004-tdd-default-methodology.md)): write a failing test, implement the minimum to pass, then refactor. Every component below has a defined test type that proves it works — tests are written *before* the implementation, never after.

| Component | Test type | What the tests prove |
|-----------|-----------|----------------------|
| Data layer (`populate_sot.py`, `seed_data.yml`) | Unit | Seed YAML is valid; upserts are idempotent (re-running does not duplicate objects); dependency ordering is respected. |
| Schema layer (`load_schemas.py`, schema YAML) | Unit | Schema YAML parses and declares the expected attributes; `SCHEMA_LOAD_ORDER` resolves dependencies before dependents. |
| Infrahub client (`client.py`, `resource_manager.py`, `models.py`) | Unit (mocked httpx) | Query/mutation payloads are well-formed; pool allocation returns the expected resource; Pydantic models validate inputs/outputs. |
| Transforms (`srlinux_*_transform.py`) | Unit + golden file | Transform output matches expected SR Linux JSON byte-for-byte for a fixed GraphQL input. |
| Checks (`*_check.py`) | Unit (mock data) | Each check flags the failure case (orphaned rules, duplicate IPs, missing interface data) and passes clean data. |
| GraphQL queries (`*.gql`) | Unit | Query shape matches what the consuming transform/check expects. |
| Config generation (`generate_configs.py`, templates) | Unit + golden file | Rendered Jinja2 output matches the committed golden file for known inputs. |
| Device I/O (`deploy_configs.py`, `validate_configs.py`) | Integration | Device accepts the config via gNMI and post-deploy state matches intent. |

Unit tests live in `tests/unit/` (no external dependencies, fast), golden files in `tests/golden/`, and integration tests in `tests/integration/` (require containerlab + Infrahub). See [adding-schemas.md](../../guides/backend/adding-schemas.md) for the test-first workflow and [python.md](../../guidelines/python.md) for conventions.

## Key Dependencies

| Package | Purpose |
|---------|---------|
| `infrahub-sdk` | Infrahub Python SDK for API interaction |
| `httpx` | HTTP client for REST/GraphQL calls |
| `jinja2` | Template rendering for SR Linux configs |
| `pyyaml` | YAML parsing for seed data and schemas |
| `pygnmi` | gNMI client for SR Linux device communication |
| `nornir` | Multi-device automation framework |
| `pydantic` | Data validation and settings management |

## Data Flow

```
seed_data.yml -> populate_sot.py -> Infrahub GraphQL API
                                          |
                   ┌──────────────────────┤
                   │                      │
           (pool allocation)      (query device data)
                   │                      │
         resource_manager.py    ┌─────────┴─────────┐
                   │            │                     │
                   │   generate_configs.py      Infrahub Transforms
                   │   + Jinja2 templates/    (server-side, --use-transforms)
                   │            │                     │
                   │            └─────────┬───────────┘
                   │                      │
                   │              (SR Linux JSON configs)
                   │                      │
                   │          deploy_configs.py -> gNMI -> SR Linux devices
                   │                      │
                   │          validate_configs.py -> gNMI GET -> validation
                   │                      │
                   └──────── Infrahub Checks (data validation)
```

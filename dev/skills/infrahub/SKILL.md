# Infrahub — Source of Truth Skill

## Metadata
- name: infrahub
- triggers: infrahub, schema, GraphQL, SoT, source of truth, seed data
- project: Network Synapse Quattro

## What is Infrahub?

Infrahub (by OpsMill) is a graph-native Source of Truth for network infrastructure. It stores schemas, inventory, and intended state with full version control and branching. NSQuattro uses Infrahub as the single source of truth for all network intent.

## SDK Async Client Patterns

Always use the async Infrahub SDK client, never raw HTTP calls:

```python
from infrahub_sdk import InfrahubClient

async def get_client() -> InfrahubClient:
    return await InfrahubClient.init(
        address="http://localhost:8000",
        api_token="<INFRAHUB_API_TOKEN>",  # See .env.example
    )
```

## Schema YAML Structure

Schemas are defined in `backend/network_synapse/schemas/*.yml`. Each schema file follows Infrahub's YAML format:

```yaml
---
version: "1.0"
nodes:
  - name: ApplicationService
    namespace: Business
    description: "Business-level service declaration"
    attributes:
      - name: name
        kind: Text
        unique: true
      - name: environment
        kind: Dropdown
        choices:
          - name: production
          - name: staging
          - name: development
    relationships:
      - name: endpoints
        peer: BusinessServiceEndpoint
        cardinality: many
        kind: Component
```

## Dependency-Ordered Loading

Schemas must be loaded in dependency order. If schema B references schema A, schema A must be loaded first. The loader in `backend/network_synapse/schemas/load_schemas.py` handles this automatically. When adding new schemas, update the load order list.

## Seed Data Upsert Pattern (Get-or-Create)

Always use idempotent upsert logic for seed data. The pattern:

```python
# Get-or-create idiom
obj = await client.get(kind="BusinessApplicationService", name__value="trading-app")
if not obj:
    obj = await client.create(kind="BusinessApplicationService", data={...})
    await obj.save()
```

Seed data lives in `backend/network_synapse/data/seed_data.yml` and is loaded via `populate_sot.py`.

## GraphQL Query Conventions

- Queries live in `backend/network_synapse/queries/`
- Use Infrahub's GraphQL schema (auto-generated from YAML schemas)
- Namespace prefix on type names: `BusinessApplicationService`, `BusinessConnectivityIntent`
- Always include `id` and `display_label` in query results

## Resource Pool Allocation

Infrahub Resource Manager handles IP/VLAN/ASN pools. Use the pool allocation pattern from `backend/network_synapse/resource_pools/`.

## Common Mistakes

- Writing synchronous HTTP calls instead of using the async SDK
- Missing schema dependency ordering (causes load failures)
- Generating invalid GraphQL queries (wrong type names, missing namespace prefix)
- Not using get-or-create for seed data (causes duplicates on re-run)

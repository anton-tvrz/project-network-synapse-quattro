# Adding Infrahub Schemas

## Overview

Infrahub schemas define the data model for network objects. Custom schema extensions live in `backend/network_synapse/schemas/` and extend base types from the `library/schema-library/` submodule.

## Steps

### 1. Create the Schema YAML

Create a new file in `backend/network_synapse/schemas/`:

```yaml
# backend/network_synapse/schemas/my_new_type.yml
---
version: "1.0"
extensions:
  nodes:
    - kind: ExistingType
      attributes:
        - name: my_new_attribute
          kind: Text
          description: "Description of the attribute"
          optional: true
```

### 2. Add to Load Order

Edit `backend/network_synapse/schemas/load_schemas.py` and add the new schema to `SCHEMA_LOAD_ORDER`:

```python
SCHEMA_LOAD_ORDER = [
    "library/schema-library/extensions/vrf/vrf.yml",
    "library/schema-library/extensions/routing/routing.yml",
    "library/schema-library/extensions/routing_bgp/bgp.yml",
    "backend/network_synapse/schemas/network_device.yml",
    "backend/network_synapse/schemas/network_interface.yml",
    "backend/network_synapse/schemas/my_new_type.yml",  # <-- Add here
]
```

### 3. Load into Infrahub

```bash
# Dry run first
uv run python backend/network_synapse/schemas/load_schemas.py --dry-run

# Load for real
uv run invoke backend.load-schemas
```

### 4. Update Seed Data (if needed)

If the schema supports new objects, add entries to `backend/network_synapse/data/seed_data.yml` and update `populate_sot.py`.

### 5. Test

Verify the schema loaded correctly via the Infrahub Web UI at `http://localhost:8000` or the GraphQL API.

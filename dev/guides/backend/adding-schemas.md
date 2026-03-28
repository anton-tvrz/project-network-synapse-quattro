# Adding Infrahub Schemas

## Overview

Infrahub schemas define the data model for network objects. Custom schema extensions live in `backend/network_synapse/schemas/` and extend base types from the `library/schema-library/` submodule.

## Steps

### 1. Write the Test File

Create `tests/unit/test_<schema_name>_schema.py` with expected validation behaviour:

```python
# tests/unit/test_my_new_type_schema.py
import yaml
import pytest

@pytest.mark.unit
def test_schema_yaml_is_valid():
    """Schema YAML must parse without errors."""
    with open("backend/network_synapse/schemas/my_new_type.yml") as f:
        schema = yaml.safe_load(f)
    assert schema["version"] == "1.0"
    assert "extensions" in schema

@pytest.mark.unit
def test_schema_has_required_attributes():
    """Schema must define the expected attributes."""
    with open("backend/network_synapse/schemas/my_new_type.yml") as f:
        schema = yaml.safe_load(f)
    nodes = schema["extensions"]["nodes"]
    assert len(nodes) > 0
    # Add assertions for specific attributes
```

Run the test — it should **fail** (RED) because the schema file doesn't exist yet.

### 2. Create the Schema YAML

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

### 3. Run Tests to Verify (GREEN)

```bash
uv run pytest tests/unit/test_my_new_type_schema.py -v
```

All tests should now pass. If not, fix the schema YAML until they do.

### 4. Add to Load Order and Update Seed Data

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

If the schema supports new objects, add entries to `backend/network_synapse/data/seed_data.yml` and update `populate_sot.py`.

### 5. Run Integration Tests

Load into Infrahub and verify end-to-end:

```bash
# Dry run first
uv run python backend/network_synapse/schemas/load_schemas.py --dry-run

# Load for real
uv run invoke backend.load-schemas

# Run integration tests
uv run invoke backend.test-integration
```

Verify the schema loaded correctly via the Infrahub Web UI at `http://localhost:8000` or the GraphQL API.

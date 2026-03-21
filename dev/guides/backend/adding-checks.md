# Adding New Checks

Step-by-step guide for creating new Infrahub data validation checks.

## 1. Create the GraphQL Query

Create a `.gql` file in `backend/network_synapse/queries/`:

```graphql
# backend/network_synapse/queries/all_my_objects.gql
query AllMyObjects {
  MyObjectType {
    edges {
      node {
        id
        name { value }
        # ... fields to validate
      }
    }
  }
}
```

## 2. Create the Check Class

Create a Python file in `backend/network_synapse/checks/`:

```python
# backend/network_synapse/checks/my_check.py
from __future__ import annotations

from infrahub_sdk.checks import InfrahubCheck


class MyCheck(InfrahubCheck):
    query = "all_my_objects"  # Must match the query name in .infrahub.yml

    async def validate(self, data: dict) -> None:
        edges = data.get("MyObjectType", {}).get("edges", [])

        if not edges:
            self.log_info(message="No objects found — nothing to validate")
            return

        for edge in edges:
            node = edge["node"]
            node_id = node.get("id", "unknown")

            # Validation logic
            name = node.get("name", {}).get("value", "")
            if not name:
                self.log_error(
                    message="Object has empty name",
                    object_id=node_id,
                    object_type="MyObjectType",
                )
```

### Key Methods

| Method | Effect |
|--------|--------|
| `self.log_error(message, object_id, object_type)` | Records an error — causes check to fail |
| `self.log_info(message)` | Records info — does not fail the check |

Errors are collected in `self.errors` and can be inspected in tests.

## 3. Register in `.infrahub.yml`

```yaml
check_definitions:
  - name: "validate_my_objects"
    file_path: "backend/network_synapse/checks/my_check.py"
    class_name: "MyCheck"

queries:
  - name: "all_my_objects"
    file_path: "backend/network_synapse/queries/all_my_objects.gql"
```

## 4. Write Unit Tests

```python
# tests/unit/test_checks.py
import pytest
from network_synapse.checks.my_check import MyCheck

@pytest.mark.unit
class TestMyCheck:
    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        check = MyCheck()
        data = {"MyObjectType": {"edges": [
            {"node": {"id": "1", "name": {"value": "valid"}}}
        ]}}
        await check.validate(data)
        assert not check.errors

    @pytest.mark.asyncio
    async def test_empty_name_fails(self):
        check = MyCheck()
        data = {"MyObjectType": {"edges": [
            {"node": {"id": "1", "name": {"value": ""}}}
        ]}}
        await check.validate(data)
        assert any("empty name" in str(e) for e in check.errors)
```

Note: `InfrahubCheck()` can be instantiated directly without arguments in unit tests.

## 5. Test Locally

```bash
# Unit tests
uv run pytest tests/unit/test_checks.py -v -k my_check

# Integration test (requires running Infrahub with seeded data)
uv run python -c "
import asyncio
from network_synapse.checks.my_check import MyCheck

async def run():
    check = MyCheck()
    data = {'MyObjectType': {'edges': [{'node': {'id': '1', 'name': {'value': 'test'}}}]}}
    await check.validate(data)
    print(f'Errors: {check.errors}')

asyncio.run(run())
"
```

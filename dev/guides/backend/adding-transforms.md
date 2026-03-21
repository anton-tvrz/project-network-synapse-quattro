# Adding New Transforms

Step-by-step guide for creating new Infrahub transforms.

## 1. Create the GraphQL Query

Create a `.gql` file in `backend/network_synapse/queries/`:

```graphql
# backend/network_synapse/queries/my_query.gql
query MyQuery($hostname: String!) {
  DcimDevice(name__value: $hostname) {
    edges {
      node {
        name { value }
        # ... fields needed by your transform
      }
    }
  }
}
```

## 2. Create the Transform Class

Create a Python file in `backend/network_synapse/transforms/`:

```python
# backend/network_synapse/transforms/my_transform.py
from __future__ import annotations

import json

from infrahub_sdk.transforms import InfrahubTransform


class MyTransform(InfrahubTransform):
    query = "my_query"  # Must match the query name in .infrahub.yml

    async def transform(self, data: dict) -> str:
        # Process the GraphQL query result
        devices = data.get("DcimDevice", {}).get("edges", [])
        if not devices:
            return json.dumps({})

        # Build your output
        result = {"key": "value"}
        return json.dumps(result, indent=2)
```

## 3. Register in `.infrahub.yml`

Add entries for both the transform and its query:

```yaml
python_transforms:
  - name: "my_transform"
    file_path: "backend/network_synapse/transforms/my_transform.py"
    class_name: "MyTransform"

queries:
  - name: "my_query"
    file_path: "backend/network_synapse/queries/my_query.gql"
```

## 4. Write Unit Tests

```python
# tests/unit/test_transforms.py
from unittest.mock import MagicMock

from network_synapse.transforms.my_transform import MyTransform

def _make_transform(cls):
    return cls(client=MagicMock(), infrahub_node=MagicMock())

async def test_my_transform():
    transform = _make_transform(MyTransform)
    data = {"DcimDevice": {"edges": [{"node": {"name": {"value": "test"}}}]}}
    result = await transform.transform(data)
    parsed = json.loads(result)
    assert "key" in parsed
```

Note: `InfrahubTransform.__init__()` requires `client` and `infrahub_node` arguments. Use `MagicMock()` in unit tests.

## 5. Test Locally

```bash
# Unit tests
uv run pytest tests/unit/test_transforms.py -v -k my_transform

# Integration test (requires running Infrahub)
uv run python -c "
from network_synapse.infrahub.client import InfrahubConfigClient
client = InfrahubConfigClient(url='http://localhost:8000')
print(client.execute_transform('my_transform', {'hostname': 'spine01'}))
client.close()
"
```

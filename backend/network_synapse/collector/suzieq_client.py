"""REST client for the SuzieQ API served by the collector stack (Issue #169).

The collector's ``suzieq-rest`` service exposes SuzieQ's parquet snapshots
over HTTP on ``localhost:8530``. This client is the single backend entry
point to that API — it fetches *assert-table* output (SuzieQ's own state
checks: BGP session state, interface status, ...) so higher layers never
talk to SuzieQ directly.

Assert endpoints follow ``/api/v2/{table}/assert`` and return a JSON array
of rows, one per checked object, each carrying a pass/fail verdict.

Configuration (``from_env``):
    SUZIEQ_REST_URL    Base URL (default http://localhost:8530)
    SUZIEQ_API_TOKEN   REST API key (matches development/suzieq/suzieq-cfg.yml)
    SUZIEQ_NAMESPACE   SuzieQ namespace to scope queries to (default spine-leaf-lab)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from types import TracebackType

DEFAULT_SUZIEQ_REST_URL = "http://localhost:8530"
DEFAULT_NAMESPACE = "spine-leaf-lab"
# Static dev-only key, mirrors development/suzieq/suzieq-cfg.yml (REST bound to
# localhost). Overridden by SUZIEQ_API_TOKEN in any real deployment.
DEFAULT_API_TOKEN = "496157e6e869ef7f3d6ecb24a6f6d847b224ee4f"  # noqa: S105  # pragma: allowlist secret


class SuzieqClient:
    """Thin HTTP client for the SuzieQ REST assert endpoints."""

    def __init__(
        self,
        url: str = DEFAULT_SUZIEQ_REST_URL,
        token: str = DEFAULT_API_TOKEN,
        namespace: str | None = DEFAULT_NAMESPACE,
        timeout: float = 30.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.namespace = namespace
        self._client = httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls) -> SuzieqClient:
        """Build a client from environment variables, falling back to dev defaults."""
        return cls(
            url=os.getenv("SUZIEQ_REST_URL", DEFAULT_SUZIEQ_REST_URL),
            token=os.getenv("SUZIEQ_API_TOKEN", DEFAULT_API_TOKEN),
            namespace=os.getenv("SUZIEQ_NAMESPACE", DEFAULT_NAMESPACE),
        )

    def assert_table(self, table: str) -> list[dict]:
        """Fetch the assert output for a SuzieQ table (e.g. ``bgp``, ``interface``).

        Returns the list of assert rows. Raises RuntimeError on any non-2xx
        response.
        """
        params: dict[str, str] = {"access_token": self.token}
        if self.namespace:
            params["namespace"] = self.namespace
        response = self._client.get(f"{self.url}/api/v2/{table}/assert", params=params)
        if response.status_code // 100 != 2:
            raise RuntimeError(f"suzieq assert {table} failed: {response.status_code} {response.text}")
        return response.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SuzieqClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

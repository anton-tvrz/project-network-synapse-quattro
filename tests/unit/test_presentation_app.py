"""Unit tests for the presentation-layer FastAPI service (Issue #170, ADR-0005).

Tests cover:
- Health endpoint requires no authentication
- Missing/unknown API keys are rejected with 401; insufficient role with 403
- POST /api/deployments starts NetworkChangeWorkflow with initiator identity in memo
- POST /api/overrides starts OperationalOverrideWorkflow with server-set operator
- Client-supplied operator fields are ignored (audit integrity)
- GET /api/workflows lists executions for viewer and operator roles
- Input validation (unknown override_type, non-positive duration)

The Temporal client is mocked via FastAPI dependency overrides — no external
dependencies are required (per ADR-0004 test types).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from synapse_presentation.app import create_app
from synapse_presentation.temporal import get_temporal_client
from temporalio.exceptions import WorkflowAlreadyStartedError

OPERATOR_KEY = "test-operator-key"
VIEWER_KEY = "test-viewer-key"
API_KEYS = f"{OPERATOR_KEY}:alice:operator,{VIEWER_KEY}:bob:viewer"


@pytest.fixture
def mock_temporal_client() -> AsyncMock:
    """A Temporal client double: start_workflow returns a handle-like object."""
    client = AsyncMock()
    handle = MagicMock()
    handle.id = "wf-id"
    handle.result_run_id = "run-id"
    client.start_workflow = AsyncMock(return_value=handle)
    return client


@pytest.fixture
def app_client(mock_temporal_client: AsyncMock) -> TestClient:
    app = create_app(api_keys=API_KEYS)
    app.dependency_overrides[get_temporal_client] = lambda: mock_temporal_client
    return TestClient(app)


def _deploy_payload() -> dict[str, Any]:
    return {"device_hostname": "leaf01", "ip_address": "172.20.20.11"}


def _override_payload() -> dict[str, Any]:
    return {
        "override_name": "maint-leaf01",
        "device_hostname": "leaf01",
        "ip_address": "172.20.20.11",
        "override_type": "maintenance_mode",
        "override_config_json": "{}",
        "reason": "planned linecard swap",
        "duration_seconds": 600,
    }


class TestHealthAndUi:
    def test_healthz_requires_no_auth(self, app_client: TestClient) -> None:
        response = app_client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_root_serves_html_ui(self, app_client: TestClient) -> None:
        response = app_client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestAuthentication:
    def test_missing_key_is_401(self, app_client: TestClient) -> None:
        response = app_client.post("/api/deployments", json=_deploy_payload())

        assert response.status_code == 401

    def test_unknown_key_is_401(self, app_client: TestClient) -> None:
        response = app_client.post(
            "/api/deployments",
            json=_deploy_payload(),
            headers={"X-API-Key": "not-a-real-key"},
        )

        assert response.status_code == 401

    def test_viewer_cannot_start_deployment(self, app_client: TestClient) -> None:
        response = app_client.post(
            "/api/deployments",
            json=_deploy_payload(),
            headers={"X-API-Key": VIEWER_KEY},
        )

        assert response.status_code == 403

    def test_viewer_cannot_start_override(self, app_client: TestClient) -> None:
        response = app_client.post(
            "/api/overrides",
            json=_override_payload(),
            headers={"X-API-Key": VIEWER_KEY},
        )

        assert response.status_code == 403

    def test_rejections_are_logged(self, app_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING", logger="synapse_presentation"):
            app_client.post(
                "/api/deployments",
                json=_deploy_payload(),
                headers={"X-API-Key": "not-a-real-key"},
            )

        assert any("rejected" in record.message.lower() for record in caplog.records)


class TestDeployments:
    def test_operator_starts_network_change_workflow(
        self, app_client: TestClient, mock_temporal_client: AsyncMock
    ) -> None:
        response = app_client.post(
            "/api/deployments",
            json=_deploy_payload(),
            headers={"X-API-Key": OPERATOR_KEY},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["workflow_id"] == "wf-id"
        assert body["run_id"] == "run-id"

        mock_temporal_client.start_workflow.assert_awaited_once()
        call = mock_temporal_client.start_workflow.await_args
        assert call.args[0] == "NetworkChangeWorkflow"
        assert call.kwargs["args"] == ["leaf01", "172.20.20.11"]
        assert call.kwargs["task_queue"] == "network-changes"
        assert call.kwargs["memo"] == {"initiated_by": "alice"}
        # Device-scoped mutex ID (Issue #165): all mutating workflows for a
        # device share one Temporal workflow ID, so concurrent starts collide.
        assert call.kwargs["id"] == "device-ops-leaf01"

    def test_busy_device_returns_409(self, app_client: TestClient, mock_temporal_client: AsyncMock) -> None:
        """A workflow already running for the device is a conflict, not a race (Issue #165)."""
        mock_temporal_client.start_workflow.side_effect = WorkflowAlreadyStartedError(
            "device-ops-leaf01", "NetworkChangeWorkflow"
        )

        response = app_client.post(
            "/api/deployments",
            json=_deploy_payload(),
            headers={"X-API-Key": OPERATOR_KEY},
        )

        assert response.status_code == 409
        assert "leaf01" in response.json()["detail"]

    def test_temporal_connect_failure_is_502(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A Temporal that is unreachable at connect time is a 502, not a 500."""

        async def _refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("connection refused")

        monkeypatch.setattr("synapse_presentation.temporal._client", None)
        monkeypatch.setattr("synapse_presentation.temporal.Client.connect", _refuse)
        app_client = TestClient(create_app(api_keys=API_KEYS), raise_server_exceptions=False)

        response = app_client.post(
            "/api/deployments",
            json=_deploy_payload(),
            headers={"X-API-Key": OPERATOR_KEY},
        )

        assert response.status_code == 502

    def test_temporal_failure_is_502(self, app_client: TestClient, mock_temporal_client: AsyncMock) -> None:
        mock_temporal_client.start_workflow.side_effect = RuntimeError("temporal unreachable")

        response = app_client.post(
            "/api/deployments",
            json=_deploy_payload(),
            headers={"X-API-Key": OPERATOR_KEY},
        )

        assert response.status_code == 502


class TestOverrides:
    def test_operator_starts_override_workflow_with_server_set_operator(
        self, app_client: TestClient, mock_temporal_client: AsyncMock
    ) -> None:
        response = app_client.post(
            "/api/overrides",
            json=_override_payload(),
            headers={"X-API-Key": OPERATOR_KEY},
        )

        assert response.status_code == 202

        call = mock_temporal_client.start_workflow.await_args
        assert call.args[0] == "OperationalOverrideWorkflow"
        override_input = call.kwargs["args"][0]
        assert override_input.operator == "alice"
        assert override_input.override_name == "maint-leaf01"
        assert override_input.duration_seconds == 600
        assert call.kwargs["memo"] == {"initiated_by": "alice"}
        # Same device mutex as deployments: an override cannot start while a
        # change is running on the device, and vice versa (Issue #165).
        assert call.kwargs["id"] == "device-ops-leaf01"

    def test_client_supplied_operator_is_ignored(self, app_client: TestClient, mock_temporal_client: AsyncMock) -> None:
        payload = _override_payload() | {"operator": "mallory"}

        app_client.post("/api/overrides", json=payload, headers={"X-API-Key": OPERATOR_KEY})

        override_input = mock_temporal_client.start_workflow.await_args.kwargs["args"][0]
        assert override_input.operator == "alice"

    def test_unknown_override_type_is_422(self, app_client: TestClient) -> None:
        payload = _override_payload() | {"override_type": "reboot_everything"}

        response = app_client.post("/api/overrides", json=payload, headers={"X-API-Key": OPERATOR_KEY})

        assert response.status_code == 422

    def test_non_positive_duration_is_422(self, app_client: TestClient) -> None:
        payload = _override_payload() | {"duration_seconds": 0}

        response = app_client.post("/api/overrides", json=payload, headers={"X-API-Key": OPERATOR_KEY})

        assert response.status_code == 422


class TestWorkflowListing:
    @staticmethod
    def _make_execution() -> MagicMock:
        execution = MagicMock()
        execution.id = "deploy-leaf01-abc123"
        execution.workflow_type = "NetworkChangeWorkflow"
        execution.status = MagicMock()
        execution.status.name = "RUNNING"
        execution.start_time = MagicMock()
        execution.start_time.isoformat = MagicMock(return_value="2026-07-10T12:00:00+00:00")
        return execution

    def _install_listing(self, client: AsyncMock) -> None:
        async def _list_workflows(*_args: Any, **_kwargs: Any) -> Any:
            yield self._make_execution()

        client.list_workflows = _list_workflows

    def test_viewer_can_list_workflows(self, app_client: TestClient, mock_temporal_client: AsyncMock) -> None:
        self._install_listing(mock_temporal_client)

        response = app_client.get("/api/workflows", headers={"X-API-Key": VIEWER_KEY})

        assert response.status_code == 200
        workflows = response.json()["workflows"]
        assert workflows == [
            {
                "workflow_id": "deploy-leaf01-abc123",
                "workflow_type": "NetworkChangeWorkflow",
                "status": "RUNNING",
                "start_time": "2026-07-10T12:00:00+00:00",
            }
        ]

    def test_listing_requires_auth(self, app_client: TestClient) -> None:
        assert app_client.get("/api/workflows").status_code == 401

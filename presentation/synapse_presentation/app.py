"""FastAPI application for self-service workflow initiation (ADR-0005).

Orchestrator-only integration: every action starts a Temporal workflow — this
service never talks to devices (gNMI) or writes to Infrahub directly. The
authenticated initiator identity is embedded in every workflow start (memo +
operator field) so it is visible in Temporal workflow history.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from temporalio.client import Client  # noqa: TC002 — FastAPI resolves Annotated[Client, ...] at runtime
from temporalio.exceptions import WorkflowAlreadyStartedError

from synapse_presentation.auth import Identity, Role, parse_api_keys, require_role
from synapse_presentation.temporal import get_temporal_client
from synapse_presentation.ui import INDEX_HTML
from synapse_workers.triggers import start_device_workflow
from synapse_workers.workflows.operational_override_workflow import OperationalOverrideInput

logger = logging.getLogger("synapse_presentation")

require_viewer = require_role(Role.VIEWER)
require_operator = require_role(Role.OPERATOR)


class DeploymentRequest(BaseModel):
    """Start the standard network change pipeline for one device."""

    device_hostname: str = Field(min_length=1)
    ip_address: str = Field(min_length=1)


class OverrideRequest(BaseModel):
    """Request a time-bounded operational override (operator is server-set)."""

    override_name: str = Field(min_length=1)
    device_hostname: str = Field(min_length=1)
    ip_address: str = Field(min_length=1)
    override_type: Literal["admin_shutdown", "maintenance_mode", "traffic_drain", "emergency_bypass"]
    override_config_json: str
    reason: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)


async def _start_workflow(client: Client, workflow: str, *, args: list, device_hostname: str, initiator: str) -> dict:
    """Start a workflow under the per-device mutex, initiator recorded in the memo.

    All mutating workflows for a device share one Temporal workflow ID
    (Issue #165), so a start while another operation runs on the device is a
    409 conflict — never a race.
    """
    try:
        handle = await start_device_workflow(
            client,
            workflow,
            device_hostname=device_hostname,
            args=args,
            memo={"initiated_by": initiator},
        )
    except WorkflowAlreadyStartedError as exc:
        logger.info("Rejected %s for %s: another operation is running", workflow, device_hostname)
        raise HTTPException(
            status_code=409,
            detail=f"Another operation is already running on {device_hostname}; retry when it completes",
        ) from exc
    except Exception as exc:
        logger.error("Failed to start %s for %s: %s", workflow, device_hostname, exc)
        raise HTTPException(status_code=502, detail="Failed to start workflow via Temporal") from exc
    logger.info("Started %s (id=%s) initiated by %s", workflow, handle.id, initiator)
    return {"workflow_id": handle.id, "run_id": handle.result_run_id}


def create_app(api_keys: str | None = None) -> FastAPI:
    """Build the presentation app; ``api_keys`` defaults to $PRESENTATION_API_KEYS."""
    app = FastAPI(
        title="NSQuattro Self-Service",
        description="Authenticated self-service initiation of network automation workflows (ADR-0005)",
        version="0.1.0",
    )
    raw_keys = api_keys if api_keys is not None else os.getenv("PRESENTATION_API_KEYS", "")
    app.state.api_keys = parse_api_keys(raw_keys)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_HTML

    @app.post("/api/deployments", status_code=202)
    async def start_deployment(
        request: DeploymentRequest,
        identity: Annotated[Identity, Depends(require_operator)],
        client: Annotated[Client, Depends(get_temporal_client)],
    ) -> dict:
        return await _start_workflow(
            client,
            "NetworkChangeWorkflow",
            args=[request.device_hostname, request.ip_address],
            device_hostname=request.device_hostname,
            initiator=identity.user,
        )

    @app.post("/api/overrides", status_code=202)
    async def start_override(
        request: OverrideRequest,
        identity: Annotated[Identity, Depends(require_operator)],
        client: Annotated[Client, Depends(get_temporal_client)],
    ) -> dict:
        override_input = OperationalOverrideInput(
            override_name=request.override_name,
            device_hostname=request.device_hostname,
            ip_address=request.ip_address,
            override_type=request.override_type,
            override_config_json=request.override_config_json,
            reason=request.reason,
            operator=identity.user,  # server-set from the authenticated identity, never client-supplied
            duration_seconds=request.duration_seconds,
        )
        return await _start_workflow(
            client,
            "OperationalOverrideWorkflow",
            args=[override_input],
            device_hostname=request.device_hostname,
            initiator=identity.user,
        )

    @app.get("/api/workflows")
    async def list_workflows(
        identity: Annotated[Identity, Depends(require_viewer)],
        client: Annotated[Client, Depends(get_temporal_client)],
        limit: int = 20,
    ) -> dict:
        workflows = []
        async for execution in client.list_workflows():
            workflows.append(
                {
                    "workflow_id": execution.id,
                    "workflow_type": execution.workflow_type,
                    "status": execution.status.name if execution.status else "UNKNOWN",
                    "start_time": execution.start_time.isoformat() if execution.start_time else None,
                }
            )
            if len(workflows) >= limit:
                break
        return {"workflows": workflows}

    return app

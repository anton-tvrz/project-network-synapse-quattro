"""Unit tests for update_device_status — client method and Temporal activity.

Covers:
  - Successful status update via GraphQL mutation
  - Invalid status raises ValueError before any API call
  - Device not found raises DeviceNotFoundError
  - GraphQL / API error handling
  - Audit log emitted on success
  - Client closed even on error (finally block)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from network_synapse.infrahub.client import (
    VALID_DEVICE_STATUSES,
    DeviceNotFoundError,
    InfrahubConfigClient,
)
from network_synapse.infrahub.models import DeviceData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MUTATION_OK_RESPONSE = {
    "DcimDeviceUpdate": {
        "ok": True,
        "object": {"id": "device-spine01-id", "display_label": "spine01"},
    },
}

MUTATION_FAIL_RESPONSE = {
    "DcimDeviceUpdate": {
        "ok": False,
        "object": None,
    },
}

EMPTY_DEVICE_RESPONSE = {"DcimDevice": {"edges": []}}


# ---------------------------------------------------------------------------
# InfrahubConfigClient.update_device_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateDeviceStatusClient:
    """Test the client method with mocked _graphql."""

    def test_successful_update(self, mock_infrahub_device_response):
        """Mutation is called and old DeviceData is returned."""
        client = InfrahubConfigClient(url="http://test:8000", token="fake")

        with patch.object(
            client,
            "_graphql",
            side_effect=[mock_infrahub_device_response, MUTATION_OK_RESPONSE],
        ) as mock_gql:
            device = client.update_device_status("spine01", "maintenance")

        assert device.name == "spine01"
        assert device.status == "active"  # old status before update
        assert mock_gql.call_count == 2

        # Verify mutation was called with correct variables
        mutation_call = mock_gql.call_args_list[1]
        variables = mutation_call.kwargs.get("variables") or mutation_call[1].get("variables")
        assert variables["data"]["status"]["value"] == "maintenance"
        assert variables["data"]["id"] == "device-spine01-id"

    def test_invalid_status_raises_valueerror(self):
        """Invalid status raises ValueError before any API call."""
        client = InfrahubConfigClient(url="http://test:8000", token="fake")

        with (
            patch.object(client, "_graphql") as mock_gql,
            pytest.raises(ValueError, match="Invalid device status"),
        ):
            client.update_device_status("spine01", "bogus")

        mock_gql.assert_not_called()

    def test_failed_status_raises_valueerror(self):
        """'failed' is not a valid Infrahub schema status."""
        client = InfrahubConfigClient(url="http://test:8000", token="fake")

        with (
            patch.object(client, "_graphql") as mock_gql,
            pytest.raises(ValueError, match="Invalid device status"),
        ):
            client.update_device_status("spine01", "failed")

        mock_gql.assert_not_called()

    def test_device_not_found(self):
        """DeviceNotFoundError when hostname does not exist."""
        client = InfrahubConfigClient(url="http://test:8000", token="fake")

        with (
            patch.object(client, "_graphql", return_value=EMPTY_DEVICE_RESPONSE),
            pytest.raises(DeviceNotFoundError),
        ):
            client.update_device_status("nonexistent", "active")

    def test_mutation_not_ok_raises_runtimeerror(self, mock_infrahub_device_response):
        """RuntimeError when mutation response has ok: false."""
        client = InfrahubConfigClient(url="http://test:8000", token="fake")

        with (
            patch.object(
                client,
                "_graphql",
                side_effect=[mock_infrahub_device_response, MUTATION_FAIL_RESPONSE],
            ),
            pytest.raises(RuntimeError, match="Failed to update status"),
        ):
            client.update_device_status("spine01", "maintenance")

    def test_graphql_error_propagates(self, mock_infrahub_device_response):
        """RuntimeError from _graphql (API error) propagates up."""
        client = InfrahubConfigClient(url="http://test:8000", token="fake")

        with (
            patch.object(
                client,
                "_graphql",
                side_effect=[
                    mock_infrahub_device_response,
                    RuntimeError("GraphQL errors: internal server error"),
                ],
            ),
            pytest.raises(RuntimeError, match="GraphQL errors"),
        ):
            client.update_device_status("spine01", "maintenance")

    def test_all_valid_statuses_accepted(self, mock_infrahub_device_response):
        """All schema-defined statuses pass validation."""
        client = InfrahubConfigClient(url="http://test:8000", token="fake")

        for status in sorted(VALID_DEVICE_STATUSES):
            with patch.object(
                client,
                "_graphql",
                side_effect=[mock_infrahub_device_response, MUTATION_OK_RESPONSE],
            ):
                device = client.update_device_status("spine01", status)
            assert device.name == "spine01"


# ---------------------------------------------------------------------------
# update_device_status activity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateDeviceStatusActivity:
    """Test the Temporal activity wrapper."""

    @pytest.mark.asyncio
    async def test_activity_calls_client_and_logs(self, mock_infrahub_device_response):
        """Activity creates client, calls update, emits audit log, closes client."""
        with (
            patch("synapse_workers.activities.infrahub_activities.InfrahubConfigClient") as mock_cls,
            patch("synapse_workers.activities.infrahub_activities.activity") as mock_activity,
        ):
            mock_client = mock_cls.return_value
            mock_client.update_device_status.return_value = DeviceData(
                id="device-spine01-id",
                name="spine01",
                description="",
                management_ip="172.20.20.3",
                lab_node_name="",
                role="spine",
                status="active",
                asn=65000,
            )

            from synapse_workers.activities.infrahub_activities import update_device_status

            await update_device_status("spine01", "maintenance")

        mock_client.update_device_status.assert_called_once_with("spine01", "maintenance")
        mock_client.close.assert_called_once()
        mock_activity.logger.info.assert_called_once()
        log_msg = mock_activity.logger.info.call_args[0][0]
        assert "Device status updated" in log_msg

    @pytest.mark.asyncio
    async def test_activity_propagates_valueerror(self):
        """ValueError from invalid status propagates (non-retryable)."""
        with patch("synapse_workers.activities.infrahub_activities.InfrahubConfigClient") as mock_cls:
            mock_client = mock_cls.return_value
            mock_client.update_device_status.side_effect = ValueError("Invalid device status")

            from synapse_workers.activities.infrahub_activities import update_device_status

            with pytest.raises(ValueError, match="Invalid device status"):
                await update_device_status("spine01", "bogus")

        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_activity_closes_client_on_error(self):
        """Client is closed even when an exception occurs (finally block)."""
        with patch("synapse_workers.activities.infrahub_activities.InfrahubConfigClient") as mock_cls:
            mock_client = mock_cls.return_value
            mock_client.update_device_status.side_effect = RuntimeError("API down")

            from synapse_workers.activities.infrahub_activities import update_device_status

            with pytest.raises(RuntimeError, match="API down"):
                await update_device_status("spine01", "active")

        mock_client.close.assert_called_once()

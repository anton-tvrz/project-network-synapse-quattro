"""Unit tests for the generate_configs CLI and transform-based generation (Issue #141).

Tests cover:
  - generate_for_device_via_transforms (dry-run, file output, transform failure)
  - generate_for_device error paths (device not found, query failure)
  - main() CLI: device resolution, transforms mode, failure exit codes,
    and Infrahub connection errors

Template rendering, JSON validation, and the generate_for_device happy path
are covered in test_config_generation.py.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

from network_synapse.infrahub.client import DeviceNotFoundError, InfrahubConfigClient
from network_synapse.scripts.generate_configs import (
    generate_for_device,
    generate_for_device_via_transforms,
    main,
)

# ---------------------------------------------------------------------------
# Transform-based generation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateViaTransforms:
    """Test config generation via Infrahub server-side transforms."""

    def _mock_client(self) -> MagicMock:
        client = MagicMock(spec=InfrahubConfigClient)
        client.execute_transform.side_effect = [
            '{"network-instance": []}',
            '{"interface": []}',
        ]
        return client

    def test_dry_run_prints_without_writing(self, tmp_path, capsys):
        client = self._mock_client()

        result = generate_for_device_via_transforms(client, "spine01", tmp_path, dry_run=True)

        assert result is True
        assert not (tmp_path / "spine01").exists()
        captured = capsys.readouterr()
        assert "spine01/bgp.json" in captured.out
        assert "spine01/interfaces.json" in captured.out

    def test_writes_both_config_files(self, tmp_path):
        client = self._mock_client()

        result = generate_for_device_via_transforms(client, "spine01", tmp_path, dry_run=False)

        assert result is True
        bgp = json.loads((tmp_path / "spine01" / "bgp.json").read_text())
        iface = json.loads((tmp_path / "spine01" / "interfaces.json").read_text())
        assert "network-instance" in bgp
        assert "interface" in iface

    def test_executes_both_transforms_with_hostname(self, tmp_path):
        client = self._mock_client()

        generate_for_device_via_transforms(client, "leaf01", tmp_path, dry_run=True)

        transform_calls = client.execute_transform.call_args_list
        assert transform_calls[0].args == ("srlinux_bgp_config", {"hostname": "leaf01"})
        assert transform_calls[1].args == ("srlinux_interface_config", {"hostname": "leaf01"})

    def test_transform_failure_returns_false(self, tmp_path, capsys):
        client = MagicMock(spec=InfrahubConfigClient)
        client.execute_transform.side_effect = RuntimeError("transform not registered")

        result = generate_for_device_via_transforms(client, "spine01", tmp_path, dry_run=False)

        assert result is False
        assert "Transform execution failed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# generate_for_device error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateForDeviceErrors:
    """Test error handling when Infrahub queries fail."""

    def test_device_not_found_returns_false(self, tmp_path, capsys):
        client = MagicMock(spec=InfrahubConfigClient)
        client.get_device_config.side_effect = DeviceNotFoundError("ghost01")

        result = generate_for_device(client, "ghost01", tmp_path, dry_run=False)

        assert result is False
        assert "not found in Infrahub" in capsys.readouterr().err

    def test_query_failure_returns_false(self, tmp_path, capsys):
        client = MagicMock(spec=InfrahubConfigClient)
        client.get_device_config.side_effect = RuntimeError("GraphQL errors: boom")

        result = generate_for_device(client, "spine01", tmp_path, dry_run=False)

        assert result is False
        assert "Failed to query Infrahub" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMainCLI:
    """Test the CLI entrypoint with the Infrahub client mocked."""

    def _run_main(self, argv: list[str], mock_client: MagicMock) -> None:
        with (
            patch.object(sys, "argv", ["generate_configs", *argv]),
            patch("network_synapse.scripts.generate_configs.InfrahubConfigClient") as mock_cls,
        ):
            mock_cls.return_value.__enter__.return_value = mock_client
            mock_cls.return_value.__exit__.return_value = False
            main()

    def test_all_devices_generates_each(self, tmp_path, capsys):
        mock_client = MagicMock(spec=InfrahubConfigClient)
        mock_client.get_all_device_hostnames.return_value = ["spine01", "leaf01"]
        with patch(
            "network_synapse.scripts.generate_configs.generate_for_device",
            return_value=True,
        ) as mock_gen:
            self._run_main(["--device", "all", "--output-dir", str(tmp_path)], mock_client)

        assert mock_gen.call_count == 2
        generated = [call.args[1] for call in mock_gen.call_args_list]
        assert generated == ["spine01", "leaf01"]
        assert "All 2 device(s) generated successfully" in capsys.readouterr().out

    def test_single_device_skips_hostname_listing(self, tmp_path):
        mock_client = MagicMock(spec=InfrahubConfigClient)
        with patch(
            "network_synapse.scripts.generate_configs.generate_for_device",
            return_value=True,
        ) as mock_gen:
            self._run_main(["--device", "spine01", "--output-dir", str(tmp_path)], mock_client)

        mock_client.get_all_device_hostnames.assert_not_called()
        assert mock_gen.call_args.args[1] == "spine01"

    def test_use_transforms_selects_transform_generator(self, tmp_path):
        mock_client = MagicMock(spec=InfrahubConfigClient)
        with (
            patch(
                "network_synapse.scripts.generate_configs.generate_for_device_via_transforms",
                return_value=True,
            ) as mock_transforms,
            patch(
                "network_synapse.scripts.generate_configs.generate_for_device",
            ) as mock_local,
        ):
            self._run_main(
                ["--device", "spine01", "--use-transforms", "--output-dir", str(tmp_path)],
                mock_client,
            )

        mock_transforms.assert_called_once()
        mock_local.assert_not_called()

    def test_failed_device_exits_nonzero(self, tmp_path, capsys):
        mock_client = MagicMock(spec=InfrahubConfigClient)
        mock_client.get_all_device_hostnames.return_value = ["spine01", "leaf01"]
        with (
            patch(
                "network_synapse.scripts.generate_configs.generate_for_device",
                side_effect=[True, False],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            self._run_main(["--device", "all", "--output-dir", str(tmp_path)], mock_client)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "leaf01: FAILED" in captured.out
        assert "1 device(s) failed" in captured.err

    def test_connection_error_exits_with_hint(self, tmp_path, capsys):
        mock_client = MagicMock(spec=InfrahubConfigClient)
        mock_client.get_all_device_hostnames.side_effect = httpx.ConnectError("refused")
        with pytest.raises(SystemExit) as exc_info:
            self._run_main(["--device", "all", "--output-dir", str(tmp_path)], mock_client)

        assert exc_info.value.code == 1
        assert "Cannot connect to Infrahub" in capsys.readouterr().err

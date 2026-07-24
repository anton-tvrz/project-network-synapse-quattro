"""Unit tests for SuzieQ drift scoring and the Prometheus exporter (Issue #74).

Converts SuzieQ assert-table output into drift metrics:
  - per-device drift score (fraction of failing assertions)
  - fleet-wide aggregate
exposed on a /metrics endpoint scraped by Prometheus (job suzieq_exporter).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from network_synapse.collector import suzieq_drift as sd

if TYPE_CHECKING:
    import pytest


class TestRowFailed:
    def test_assert_fail_is_a_failure(self) -> None:
        assert sd.row_failed({"hostname": "spine01", "assert": "fail"}) is True

    def test_assert_pass_is_not_a_failure(self) -> None:
        assert sd.row_failed({"hostname": "spine01", "assert": "pass"}) is False

    def test_case_insensitive(self) -> None:
        assert sd.row_failed({"assert": "FAIL"}) is True

    def test_result_field_alias(self) -> None:
        # Some SuzieQ versions label the status column "result".
        assert sd.row_failed({"hostname": "leaf01", "result": "fail"}) is True

    def test_missing_status_is_not_a_failure(self) -> None:
        assert sd.row_failed({"hostname": "leaf01"}) is False


class TestDriftScoreByDevice:
    def test_scores_fraction_of_failing_assertions_per_device(self) -> None:
        rows = [
            {"hostname": "spine01", "assert": "pass"},
            {"hostname": "spine01", "assert": "fail"},
            {"hostname": "leaf01", "assert": "fail"},
            {"hostname": "leaf01", "assert": "fail"},
        ]
        scores = sd.drift_score_by_device(rows)
        assert scores == {"spine01": 0.5, "leaf01": 1.0}

    def test_all_passing_scores_zero(self) -> None:
        rows = [{"hostname": "leaf02", "assert": "pass"}]
        assert sd.drift_score_by_device(rows) == {"leaf02": 0.0}

    def test_rows_without_hostname_are_ignored(self) -> None:
        rows = [{"assert": "fail"}, {"hostname": "spine01", "assert": "pass"}]
        assert sd.drift_score_by_device(rows) == {"spine01": 0.0}

    def test_empty_input_yields_no_scores(self) -> None:
        assert sd.drift_score_by_device([]) == {}


class TestDriftScoreAggregate:
    def test_mean_of_device_scores(self) -> None:
        assert sd.drift_score_aggregate({"spine01": 0.5, "leaf01": 1.0}) == 0.75

    def test_empty_fleet_scores_zero(self) -> None:
        assert sd.drift_score_aggregate({}) == 0.0


class TestCollectDrift:
    def test_unions_assert_rows_across_all_tables(self) -> None:
        client = MagicMock(spec=sd.SuzieqClient)
        client.assert_table.side_effect = lambda table: {
            "bgp": [{"hostname": "spine01", "assert": "fail"}],
            "interface": [{"hostname": "spine01", "assert": "pass"}],
        }[table]

        scores = sd.collect_drift(client)

        assert scores == {"spine01": 0.5}
        assert [c.args[0] for c in client.assert_table.call_args_list] == list(sd.ASSERT_TABLES)


class TestUpdateGauges:
    def test_sets_per_device_and_aggregate_gauges(self) -> None:
        sd.update_gauges({"spine01": 0.5, "leaf01": 1.0})
        samples = {
            (s.labels.get("device"), s.name): s.value for metric in sd.REGISTRY.collect() for s in metric.samples
        }
        assert samples[("spine01", "suzieq_drift_score")] == 0.5
        assert samples[("leaf01", "suzieq_drift_score")] == 1.0
        assert samples[(None, "suzieq_drift_score_aggregate")] == 0.75

    def test_stale_devices_are_cleared_between_refreshes(self) -> None:
        sd.update_gauges({"spine01": 1.0})
        sd.update_gauges({"leaf01": 0.0})
        devices = {
            s.labels["device"]
            for metric in sd.REGISTRY.collect()
            for s in metric.samples
            if s.name == "suzieq_drift_score"
        }
        assert devices == {"leaf01"}


class TestMain:
    def test_dry_run_prints_scores_without_serving(self, capsys: pytest.CaptureFixture) -> None:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        with (
            patch.object(sd.SuzieqClient, "from_env", return_value=client),
            patch.object(sd, "collect_drift", return_value={"spine01": 0.5}),
            patch.object(sd, "start_http_server") as mock_serve,
        ):
            rc = sd.main(["--dry-run"])
        assert rc == 0
        mock_serve.assert_not_called()
        assert "spine01" in capsys.readouterr().out

    def test_failure_returns_nonzero(self) -> None:
        with patch.object(sd.SuzieqClient, "from_env", side_effect=RuntimeError("boom")):
            assert sd.main(["--dry-run"]) == 1

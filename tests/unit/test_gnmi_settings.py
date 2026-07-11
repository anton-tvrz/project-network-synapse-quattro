"""Unit tests for gNMI transport settings and credential resolution (Issue #166).

The settings module is the single place where:
  - the TLS posture of every gNMI connection is decided (GNMI_TLS_MODE), and
  - device credentials are resolved (GNMI_USERNAME / GNMI_PASSWORD),

so that ``insecure=True`` stops being baked in as the only mode, and secrets
are resolved inside activities instead of riding through Temporal workflow
history as activity arguments.
"""

from __future__ import annotations

import pytest

from network_synapse.gnmi_settings import device_credentials, gnmi_connection_kwargs


@pytest.mark.unit
class TestGnmiConnectionKwargs:
    def test_defaults_to_insecure_for_local_lab(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GNMI_TLS_MODE", raising=False)

        assert gnmi_connection_kwargs() == {"insecure": True}

    def test_insecure_mode_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GNMI_TLS_MODE", "insecure")

        assert gnmi_connection_kwargs() == {"insecure": True}

    def test_skip_verify_mode_enables_tls_without_verification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TLS with skip-verify is what a containerlab-default SR Linux needs."""
        monkeypatch.setenv("GNMI_TLS_MODE", "skip-verify")

        assert gnmi_connection_kwargs() == {"skip_verify": True}

    def test_ca_cert_mode_verifies_against_provided_root(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        ca = tmp_path / "ca.pem"
        ca.write_text("dummy")
        monkeypatch.setenv("GNMI_TLS_MODE", "ca-cert")
        monkeypatch.setenv("GNMI_CA_CERT", str(ca))

        assert gnmi_connection_kwargs() == {"path_root": str(ca)}

    def test_ca_cert_mode_without_cert_path_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GNMI_TLS_MODE", "ca-cert")
        monkeypatch.delenv("GNMI_CA_CERT", raising=False)

        with pytest.raises(ValueError, match="GNMI_CA_CERT"):
            gnmi_connection_kwargs()

    def test_unknown_mode_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typo in the TLS mode must not silently fall back to plaintext."""
        monkeypatch.setenv("GNMI_TLS_MODE", "plz-encrypt")

        with pytest.raises(ValueError, match="GNMI_TLS_MODE"):
            gnmi_connection_kwargs()

    def test_mode_is_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GNMI_TLS_MODE", "Skip-Verify")

        assert gnmi_connection_kwargs() == {"skip_verify": True}


@pytest.mark.unit
class TestDeviceCredentials:
    def test_lab_defaults_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GNMI_USERNAME", raising=False)
        monkeypatch.delenv("GNMI_PASSWORD", raising=False)

        assert device_credentials() == ("admin", "NokiaSrl1!")

    def test_env_overrides_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GNMI_USERNAME", "svc-automation")
        monkeypatch.setenv("GNMI_PASSWORD", "s3cret")

        assert device_credentials() == ("svc-automation", "s3cret")

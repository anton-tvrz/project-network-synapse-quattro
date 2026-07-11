"""Guard: no Temporal activity may accept credential-bearing arguments (Issue #166).

Temporal persists every activity input in workflow event history, unencrypted
by default and readable via the Web UI and API. The only reliable way to keep
secrets out of history is for no activity signature to accept one — credentials
are resolved inside the activity from the environment instead
(``network_synapse.gnmi_settings.device_credentials``).

This test walks every module under ``synapse_workers.activities``, finds every
``@activity.defn`` function, and fails if any parameter name looks like a
credential. It is intentionally name-based: a new activity with a ``password``
parameter should fail loudly here before it ever ships.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import synapse_workers.activities as activities_pkg

CREDENTIAL_PARAM_NAMES = {"password", "passwd", "username", "user", "secret", "token", "api_key", "apikey"}


def _all_activity_functions():
    for module_info in pkgutil.iter_modules(activities_pkg.__path__):
        module = importlib.import_module(f"{activities_pkg.__name__}.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isfunction):
            if hasattr(obj, "__temporal_activity_definition"):
                yield obj


@pytest.mark.unit
def test_activities_are_discovered() -> None:
    """The walker must actually find the registered activities, or the guard is vacuous."""
    names = {fn.__name__ for fn in _all_activity_functions()}

    assert {"backup_running_config", "deploy_config", "rollback_config", "fetch_running_config"} <= names


@pytest.mark.unit
def test_no_activity_accepts_credential_arguments() -> None:
    offenders = []
    for fn in _all_activity_functions():
        params = set(inspect.signature(fn).parameters)
        leaked = params & CREDENTIAL_PARAM_NAMES
        if leaked:
            offenders.append(f"{fn.__module__}.{fn.__name__}({', '.join(sorted(leaked))})")

    assert not offenders, (
        "Activity signatures accept credentials, which Temporal would persist "
        f"in workflow history: {offenders}. Resolve credentials inside the "
        "activity via network_synapse.gnmi_settings.device_credentials() instead."
    )

"""Override-aware state validation against SuzieQ observations (Issue #64).

During an operational override (``OperationalOverride``, Issue #161) some
device objects are intentionally down — that is the sanctioned deviation.
Validating device health against the plain SoT intent would therefore flag
the deviation itself as a fault. This module compares SuzieQ's *independent*
observed state against an **override-aware** expected state:

  - a targeted object the override is meant to take down is expected DOWN;
    observing it still up means the sanctioned change never took effect
    (``override_ineffective``).
  - every other object is expected healthy; observing it down is collateral
    damage the override does not explain (``unexpected_down``).

SuzieQ is the source of truth for observed state here (via ``suzieq_client``),
keeping the check independent of the device's own gNMI answer — the intent
of "SuzieQ as an independent validation layer" in Issue #64.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Override types whose targeted object is intentionally taken down. Reflects
# this lab's operational model (the fibre-outage / BGP admin-shutdown scenario,
# Issue #51); refine per-type as more scenarios are modelled.
_TARGET_DOWN_TYPES = frozenset({"admin_shutdown", "maintenance_mode", "traffic_drain"})

# Verdict statuses.
CONSISTENT = "consistent"
OVERRIDE_INEFFECTIVE = "override_ineffective"
UNEXPECTED_DOWN = "unexpected_down"


@dataclass
class ObjectVerdict:
    """The override-aware verdict for a single observed object."""

    object_id: str  # BGP peer address or interface name
    kind: str  # "bgp" | "interface"
    observed_up: bool
    expected_up: bool
    status: str


@dataclass
class ValidationResult:
    """Outcome of validating a device's state against an active override."""

    device: str
    consistent: bool
    verdicts: list[ObjectVerdict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for transport across a Temporal activity boundary."""
        return asdict(self)


def override_expects_target_down(override_type: str) -> bool:
    """Whether an override of this type intentionally takes its target down."""
    return override_type in _TARGET_DOWN_TYPES


def _bgp_established(row: dict) -> bool:
    return str(row.get("state", "")).lower() == "established"


def _interface_up(row: dict) -> bool:
    return str(row.get("state", "")).lower() == "up"


def _verdict(object_id: str, kind: str, observed_up: bool, expected_up: bool) -> ObjectVerdict:
    if observed_up == expected_up:
        status = CONSISTENT
    elif expected_up:
        # Expected healthy but observed down — the override can't explain this.
        status = UNEXPECTED_DOWN
    else:
        # Expected down (sanctioned) but observed up — the change never landed.
        status = OVERRIDE_INEFFECTIVE
    return ObjectVerdict(
        object_id=object_id, kind=kind, observed_up=observed_up, expected_up=expected_up, status=status
    )


def validate_override_state(
    device: str,
    override_type: str,
    target_bgp_peers: Iterable[str],
    target_interfaces: Iterable[str],
    bgp_rows: list[dict],
    interface_rows: list[dict],
) -> ValidationResult:
    """Validate SuzieQ-observed state against override-aware expectations.

    Args:
        device: Hostname the override applies to; rows for other hosts are ignored.
        override_type: OperationalOverride type driving the expected state.
        target_bgp_peers: Peer addresses the override targets.
        target_interfaces: Interface names the override targets.
        bgp_rows: SuzieQ ``bgp show`` rows (hostname, peer, state).
        interface_rows: SuzieQ ``interface show`` rows (hostname, ifname, state).

    Returns:
        A ValidationResult; ``consistent`` is True only when every object
        matches its override-aware expected state.
    """
    target_down = override_expects_target_down(override_type)
    bgp_targets = set(target_bgp_peers)
    iface_targets = set(target_interfaces)
    verdicts: list[ObjectVerdict] = []

    for row in bgp_rows:
        if row.get("hostname") != device:
            continue
        peer = row.get("peer", "")
        expected_up = not (target_down and peer in bgp_targets)
        verdicts.append(_verdict(peer, "bgp", _bgp_established(row), expected_up))

    for row in interface_rows:
        if row.get("hostname") != device:
            continue
        ifname = row.get("ifname", "")
        expected_up = not (target_down and ifname in iface_targets)
        verdicts.append(_verdict(ifname, "interface", _interface_up(row), expected_up))

    consistent = all(v.status == CONSISTENT for v in verdicts)
    return ValidationResult(device=device, consistent=consistent, verdicts=verdicts)

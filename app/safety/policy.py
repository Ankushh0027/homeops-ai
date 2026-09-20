"""
app/safety/policy.py
====================
Deterministic safety policy evaluator.

This module contains the single source of truth for what HomeOps is allowed
to do in response to an incident.  Every decision is produced by an explicit
rule table – there is no probabilistic or LLM-based reasoning here.

Policy table
------------
+-----------+-----------------------------+----------------------------------+
| Risk level| Action permission           | Autonomous physical action?      |
+===========+=============================+==================================+
| LOW       | Informational only          | Allowed (information only)       |
| MEDIUM    | Requires user confirmation  | NOT allowed without confirmation |
| HIGH      | Requires explicit approval  | Only predefined safe actions     |
| CRITICAL  | No autonomous action        | STRICTLY PROHIBITED              |
+-----------+-----------------------------+----------------------------------+

Design decisions
----------------
* The function ``evaluate_policy`` is pure: same inputs → same output.
* ``execute_safe_action`` is the ONLY gateway through which the system
  could ever trigger a device-level action.  In the MVP it ALWAYS raises
  ``AutonomousActionForbiddenError``, ensuring no accidental integration
  can cause physical side-effects.
* Risk level is derived mechanically from incident severity – not inferred.
* Audit trail entries include UTC timestamps so they can be persisted later.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.incidents.schemas import Incident, IncidentType, Severity
from app.safety.schemas import ActionPermission, RiskLevel, SafetyDecision

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AutonomousActionForbiddenError(RuntimeError):
    """Raised when code attempts to execute a physical action automatically.

    This error is intentional and is part of the safety architecture.
    It is not a bug – it is a guard rail that must never be removed without
    an explicit safety review and human approval workflow in place.
    """


# ---------------------------------------------------------------------------
# Severity → Risk level mapping
# ---------------------------------------------------------------------------

_SEVERITY_TO_RISK: dict[Severity, RiskLevel] = {
    Severity.LOW: RiskLevel.LOW,
    Severity.MEDIUM: RiskLevel.MEDIUM,
    Severity.HIGH: RiskLevel.HIGH,
    Severity.CRITICAL: RiskLevel.CRITICAL,
}


def _now_label() -> str:
    """Return a compact UTC timestamp label for audit trail entries."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Predefined safe actions per incident type
# ---------------------------------------------------------------------------

# These are *suggestions* surfaced to the user, never executed automatically.
_SAFE_ACTIONS: dict[IncidentType, list[str]] = {
    IncidentType.SECURITY: [
        "Review camera footage for the affected entry point.",
        "Verify with a household member whether they entered the property.",
        "Arm the security system (requires your confirmation in the app).",
        "Contact emergency services if intrusion is confirmed.",
    ],
    IncidentType.WATER_HAZARD: [
        "Visually inspect the affected area for standing water.",
        "Turn off the water main manually if safe to do so.",
        "Stop the running appliance if safe to do so.",
        "Contact a licensed plumber.",
        "Move valuable items away from the affected area.",
    ],
    IncidentType.LEAVING_HOME: [
        "Close and lock all open doors/windows before leaving.",
        "Stop any running appliances.",
        "Arm the security system.",
        "Turn off lights in unoccupied rooms.",
    ],
    IncidentType.UNKNOWN: [
        "Review recent device activity in your home management app.",
    ],
}


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------


def evaluate_policy(incident: Incident) -> SafetyDecision:
    """Evaluate the safety policy for a given incident.

    Parameters
    ----------
    incident:
        A correlated incident produced by the incident engine.

    Returns
    -------
    SafetyDecision
        A fully structured, immutable safety decision.
    """
    risk_level = _SEVERITY_TO_RISK[incident.severity]
    audit: list[str] = []

    audit.append(
        f"[{_now_label()}] evaluate_policy called for incident "
        f"'{incident.incident_id}' "
        f"(type={incident.incident_type.value}, severity={incident.severity.value})."
    )

    # ------------------------------------------------------------------ #
    # Policy rules – explicit, ordered, exhaustive                        #
    # ------------------------------------------------------------------ #

    if risk_level == RiskLevel.LOW:
        audit.append(
            f"[{_now_label()}] RULE LOW-1: Risk level is LOW. "
            "Informational response permitted without user confirmation."
        )
        decision = SafetyDecision(
            risk_level=risk_level,
            action_permission=ActionPermission.INFORMATIONAL_ONLY,
            action_permitted=True,
            requires_user_confirmation=False,
            requires_explicit_approval=False,
            escalation_required=False,
            allowed_actions=_SAFE_ACTIONS.get(incident.incident_type, []),
            policy_rationale=(
                "Risk level is LOW. An informational response may be delivered. "
                "No physical action is needed at this time."
            ),
            audit_trail=audit,
        )

    elif risk_level == RiskLevel.MEDIUM:
        audit.append(
            f"[{_now_label()}] RULE MED-1: Risk level is MEDIUM. "
            "User confirmation required before any action."
        )
        decision = SafetyDecision(
            risk_level=risk_level,
            action_permission=ActionPermission.REQUIRES_USER_CONFIRMATION,
            action_permitted=False,
            requires_user_confirmation=True,
            requires_explicit_approval=False,
            escalation_required=False,
            allowed_actions=_SAFE_ACTIONS.get(incident.incident_type, []),
            policy_rationale=(
                "Risk level is MEDIUM. No action may proceed without explicit "
                "user confirmation via an approved interface."
            ),
            audit_trail=audit,
        )

    elif risk_level == RiskLevel.HIGH:
        audit.append(
            f"[{_now_label()}] RULE HIGH-1: Risk level is HIGH. "
            "Explicit approval required; only predefined safe actions may be presented."
        )
        decision = SafetyDecision(
            risk_level=risk_level,
            action_permission=ActionPermission.REQUIRES_EXPLICIT_APPROVAL,
            action_permitted=False,
            requires_user_confirmation=True,
            requires_explicit_approval=True,
            escalation_required=False,
            allowed_actions=_SAFE_ACTIONS.get(incident.incident_type, []),
            policy_rationale=(
                "Risk level is HIGH. Only predefined, pre-vetted safe actions may "
                "be presented to the user.  Explicit approval is required before "
                "any action is taken.  Autonomous physical action is prohibited."
            ),
            audit_trail=audit,
        )

    else:  # CRITICAL
        audit.append(
            f"[{_now_label()}] RULE CRIT-1: Risk level is CRITICAL. "
            "Autonomous physical action STRICTLY PROHIBITED. Escalation only."
        )
        decision = SafetyDecision(
            risk_level=risk_level,
            action_permission=ActionPermission.NO_AUTONOMOUS_ACTION,
            action_permitted=False,
            requires_user_confirmation=True,
            requires_explicit_approval=True,
            escalation_required=True,
            allowed_actions=[],
            policy_rationale=(
                "Risk level is CRITICAL. No autonomous action of any kind is "
                "permitted.  The system will provide information and escalation "
                "channels only.  A human operator must take control."
            ),
            audit_trail=audit,
        )

    logger.info(
        "Policy decision for incident %s: risk=%s, permission=%s",
        incident.incident_id,
        decision.risk_level.value,
        decision.action_permission.value,
    )
    return decision


# ---------------------------------------------------------------------------
# Action gateway – MVP guard rail
# ---------------------------------------------------------------------------


def execute_safe_action(action_name: str, **kwargs: object) -> None:  # noqa: ARG001
    """Gateway function that would eventually execute an approved safe action.

    In the MVP this function ALWAYS raises ``AutonomousActionForbiddenError``.
    This is intentional: no physical device action may be executed
    automatically.  Future phases will gate calls through this function only
    after a full human-in-the-loop approval flow is in place.

    Parameters
    ----------
    action_name:
        Name of the requested action (e.g. ``'arm_security_system'``).
    **kwargs:
        Action-specific parameters (ignored in MVP).

    Raises
    ------
    AutonomousActionForbiddenError
        Always.  Physical actions are prohibited in the MVP.
    """
    raise AutonomousActionForbiddenError(
        f"Autonomous physical action '{action_name}' is PROHIBITED in the MVP. "
        "All physical actions require explicit human approval via an approved "
        "interface.  This guard rail must not be removed without a full safety review."
    )

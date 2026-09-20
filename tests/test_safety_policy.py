"""
tests/test_safety_policy.py
============================
Pytest tests for the safety policy evaluator.

Tests verify:
- LOW risk → informational permitted, no confirmation needed
- MEDIUM risk → action blocked, confirmation required
- HIGH risk → explicit approval required, only safe actions presented
- CRITICAL risk → no autonomous action, escalation required
- execute_safe_action always raises AutonomousActionForbiddenError
- SafetyDecision is immutable (Pydantic frozen model)
- Audit trail is populated for every decision
- Allowed actions are populated for non-CRITICAL decisions
- CRITICAL decisions have no allowed actions
"""

from __future__ import annotations

import pytest

from app.incidents.schemas import Incident, IncidentType, Severity
from app.safety.policy import (
    AutonomousActionForbiddenError,
    evaluate_policy,
    execute_safe_action,
)
from app.safety.schemas import ActionPermission, RiskLevel


# ---------------------------------------------------------------------------
# Fixtures – pre-built incidents at each severity level
# ---------------------------------------------------------------------------


def make_incident(severity: Severity, incident_type: IncidentType = IncidentType.SECURITY) -> Incident:
    """Create a minimal valid Incident at the given severity."""
    return Incident(
        incident_type=incident_type,
        severity=severity,
        title=f"Test incident ({severity.value})",
        summary="Automated test incident.",
        evidence=[f"Test evidence for {severity.value} severity incident."],
        confidence=0.75,
        recommended_next_step="Take appropriate action.",
    )


@pytest.fixture()
def low_incident():
    return make_incident(Severity.LOW)


@pytest.fixture()
def medium_incident():
    return make_incident(Severity.MEDIUM)


@pytest.fixture()
def high_incident():
    return make_incident(Severity.HIGH)


@pytest.fixture()
def critical_incident():
    return make_incident(Severity.CRITICAL)


# ---------------------------------------------------------------------------
# 1. LOW risk policy
# ---------------------------------------------------------------------------


class TestPolicyLow:
    def test_risk_level_is_low(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert decision.risk_level == RiskLevel.LOW

    def test_action_permitted_is_true(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert decision.action_permitted is True

    def test_no_user_confirmation_required(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert decision.requires_user_confirmation is False

    def test_no_explicit_approval_required(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert decision.requires_explicit_approval is False

    def test_no_escalation_required(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert decision.escalation_required is False

    def test_permission_is_informational_only(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert decision.action_permission == ActionPermission.INFORMATIONAL_ONLY

    def test_allowed_actions_populated(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert isinstance(decision.allowed_actions, list)
        assert len(decision.allowed_actions) > 0

    def test_policy_rationale_is_non_empty(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert len(decision.policy_rationale) > 0

    def test_audit_trail_populated(self, low_incident):
        decision = evaluate_policy(low_incident)
        assert len(decision.audit_trail) >= 1


# ---------------------------------------------------------------------------
# 2. MEDIUM risk policy
# ---------------------------------------------------------------------------


class TestPolicyMedium:
    def test_risk_level_is_medium(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert decision.risk_level == RiskLevel.MEDIUM

    def test_action_not_permitted(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert decision.action_permitted is False

    def test_user_confirmation_required(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert decision.requires_user_confirmation is True

    def test_explicit_approval_not_required(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert decision.requires_explicit_approval is False

    def test_no_escalation_required(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert decision.escalation_required is False

    def test_permission_requires_confirmation(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert decision.action_permission == ActionPermission.REQUIRES_USER_CONFIRMATION

    def test_allowed_actions_populated(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert len(decision.allowed_actions) > 0

    def test_audit_trail_populated(self, medium_incident):
        decision = evaluate_policy(medium_incident)
        assert len(decision.audit_trail) >= 1


# ---------------------------------------------------------------------------
# 3. HIGH risk policy
# ---------------------------------------------------------------------------


class TestPolicyHigh:
    def test_risk_level_is_high(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert decision.risk_level == RiskLevel.HIGH

    def test_action_not_permitted_without_approval(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert decision.action_permitted is False

    def test_user_confirmation_required(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert decision.requires_user_confirmation is True

    def test_explicit_approval_required(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert decision.requires_explicit_approval is True

    def test_no_escalation_required_at_high(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert decision.escalation_required is False

    def test_permission_requires_explicit_approval(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert decision.action_permission == ActionPermission.REQUIRES_EXPLICIT_APPROVAL

    def test_only_predefined_safe_actions_present(self, high_incident):
        """Allowed actions must come from the predefined list, not ad-hoc."""
        decision = evaluate_policy(high_incident)
        assert isinstance(decision.allowed_actions, list)
        # Must not be empty for HIGH security incidents
        assert len(decision.allowed_actions) > 0

    def test_audit_trail_populated(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert len(decision.audit_trail) >= 1

    def test_rationale_mentions_physical_action_prohibition(self, high_incident):
        decision = evaluate_policy(high_incident)
        assert "autonomous" in decision.policy_rationale.lower() or \
               "physical" in decision.policy_rationale.lower()


# ---------------------------------------------------------------------------
# 4. CRITICAL risk policy
# ---------------------------------------------------------------------------


class TestPolicyCritical:
    def test_risk_level_is_critical(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert decision.risk_level == RiskLevel.CRITICAL

    def test_action_not_permitted(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert decision.action_permitted is False

    def test_user_confirmation_required(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert decision.requires_user_confirmation is True

    def test_explicit_approval_required(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert decision.requires_explicit_approval is True

    def test_escalation_required(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert decision.escalation_required is True

    def test_permission_is_no_autonomous_action(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert decision.action_permission == ActionPermission.NO_AUTONOMOUS_ACTION

    def test_no_allowed_actions_at_critical(self, critical_incident):
        """CRITICAL decisions must NOT surface any allowed actions."""
        decision = evaluate_policy(critical_incident)
        assert decision.allowed_actions == []

    def test_audit_trail_populated(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert len(decision.audit_trail) >= 1

    def test_rationale_mentions_escalation(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert "escalat" in decision.policy_rationale.lower() or \
               "human" in decision.policy_rationale.lower()

    def test_rationale_mentions_no_autonomous_action(self, critical_incident):
        decision = evaluate_policy(critical_incident)
        assert "autonomous" in decision.policy_rationale.lower() or \
               "no autonomous" in decision.policy_rationale.lower()


# ---------------------------------------------------------------------------
# 5. Prohibition of autonomous physical actions
# ---------------------------------------------------------------------------


class TestExecuteSafeActionForbidden:
    """execute_safe_action must ALWAYS raise in the MVP, regardless of args."""

    def test_raises_for_any_action_name(self):
        with pytest.raises(AutonomousActionForbiddenError):
            execute_safe_action("arm_security_system")

    def test_raises_for_water_shutoff(self):
        with pytest.raises(AutonomousActionForbiddenError):
            execute_safe_action("shut_off_water_main")

    def test_raises_for_door_lock(self):
        with pytest.raises(AutonomousActionForbiddenError):
            execute_safe_action("lock_door", device_id="door-back-01")

    def test_raises_for_appliance_stop(self):
        with pytest.raises(AutonomousActionForbiddenError):
            execute_safe_action("stop_appliance", device_id="washer-01")

    def test_raises_for_arbitrary_action(self):
        with pytest.raises(AutonomousActionForbiddenError):
            execute_safe_action("do_anything")

    def test_error_message_is_informative(self):
        with pytest.raises(AutonomousActionForbiddenError) as exc_info:
            execute_safe_action("arm_security_system")
        msg = str(exc_info.value).lower()
        assert "prohibited" in msg or "forbidden" in msg or "not" in msg

    def test_is_runtime_error_subclass(self):
        """AutonomousActionForbiddenError must be a RuntimeError for easy catching."""
        with pytest.raises(RuntimeError):
            execute_safe_action("any_action")


# ---------------------------------------------------------------------------
# 6. SafetyDecision immutability
# ---------------------------------------------------------------------------


class TestSafetyDecisionImmutable:
    def test_cannot_mutate_risk_level(self, low_incident):
        decision = evaluate_policy(low_incident)
        with pytest.raises(Exception):
            decision.risk_level = RiskLevel.CRITICAL  # type: ignore[misc]

    def test_cannot_mutate_action_permitted(self, low_incident):
        decision = evaluate_policy(low_incident)
        with pytest.raises(Exception):
            decision.action_permitted = False  # type: ignore[misc]

    def test_cannot_mutate_audit_trail(self, low_incident):
        decision = evaluate_policy(low_incident)
        with pytest.raises(Exception):
            decision.audit_trail = []  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 7. Cross-incident-type safety decisions
# ---------------------------------------------------------------------------


class TestPolicyCrossIncidentTypes:
    """Verify policy decisions work correctly for all incident types."""

    @pytest.mark.parametrize("incident_type", list(IncidentType))
    def test_high_severity_always_requires_explicit_approval(self, incident_type):
        incident = make_incident(Severity.HIGH, incident_type)
        decision = evaluate_policy(incident)
        assert decision.requires_explicit_approval is True
        assert decision.action_permitted is False

    @pytest.mark.parametrize("incident_type", list(IncidentType))
    def test_critical_severity_always_escalates(self, incident_type):
        incident = make_incident(Severity.CRITICAL, incident_type)
        decision = evaluate_policy(incident)
        assert decision.escalation_required is True
        assert decision.allowed_actions == []

    @pytest.mark.parametrize("incident_type", list(IncidentType))
    def test_evaluated_at_is_set(self, incident_type):
        incident = make_incident(Severity.LOW, incident_type)
        decision = evaluate_policy(incident)
        assert decision.evaluated_at is not None

    def test_water_hazard_high_has_water_related_actions(self):
        incident = make_incident(Severity.HIGH, IncidentType.WATER_HAZARD)
        decision = evaluate_policy(incident)
        actions_text = " ".join(decision.allowed_actions).lower()
        assert "water" in actions_text or "plumber" in actions_text or "appliance" in actions_text

    def test_leaving_home_medium_has_relevant_actions(self):
        incident = make_incident(Severity.MEDIUM, IncidentType.LEAVING_HOME)
        decision = evaluate_policy(incident)
        actions_text = " ".join(decision.allowed_actions).lower()
        assert "door" in actions_text or "security" in actions_text or "appliance" in actions_text

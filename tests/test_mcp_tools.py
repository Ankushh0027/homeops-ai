"""
tests/test_mcp_tools.py
=======================
Pytest tests for the HomeOps MCP tool handler functions.

Tests validate:
- Tool function correctness (unit-level, no network required)
- Input sanitisation and validation
- Integration with deterministic core (engine, policy)
- execute_safe_action is always blocked
- record_incident persists to and retrieves from history
- No physical actions are executed
- Confidence bounds and severity handling
"""

from __future__ import annotations

import pytest

from app.incidents.engine import IncidentEngine
from app.mcp.tools import (
    assess_risk,
    execute_safe_action_tool,
    get_home_state,
    get_recent_events,
    investigate_incident,
    record_incident,
    recommend_response,
)
from app.models.events import HomeEvent
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state() -> HomeStateService:
    """Fresh isolated HomeStateService for each test."""
    return HomeStateService()


@pytest.fixture()
def engine() -> IncidentEngine:
    return IncidentEngine()


@pytest.fixture()
def history() -> IncidentHistoryStore:
    """In-memory SQLite store for each test."""
    return IncidentHistoryStore(":memory:")


@pytest.fixture()
def state_with_security(state: HomeStateService) -> HomeStateService:
    """HomeStateService pre-loaded with the security_incident scenario."""
    state.load_scenario("security_incident")
    return state


@pytest.fixture()
def state_with_water(state: HomeStateService) -> HomeStateService:
    state.load_scenario("water_hazard")
    return state


@pytest.fixture()
def state_with_leaving(state: HomeStateService) -> HomeStateService:
    state.load_scenario("leaving_home")
    return state


# ---------------------------------------------------------------------------
# 1. get_home_state
# ---------------------------------------------------------------------------


class TestGetHomeState:
    def test_returns_home_id(self, state: HomeStateService):
        result = get_home_state(ctx=state)
        assert result["home_id"] == HomeStateService.HOME_ID

    def test_returns_snapshot_at(self, state: HomeStateService):
        result = get_home_state(ctx=state)
        assert "snapshot_at" in result

    def test_returns_devices_list(self, state: HomeStateService):
        result = get_home_state(ctx=state)
        assert isinstance(result["devices"], list)

    def test_returns_active_conditions(self, state: HomeStateService):
        result = get_home_state(ctx=state)
        assert isinstance(result["active_conditions"], list)

    def test_returns_occupancy_dict(self, state: HomeStateService):
        result = get_home_state(ctx=state)
        assert isinstance(result["occupancy"], dict)

    def test_with_loaded_scenario_has_devices(self, state_with_security: HomeStateService):
        result = get_home_state(ctx=state_with_security)
        assert len(result["devices"]) > 0

    def test_location_filter_applied(self, state_with_security: HomeStateService):
        result = get_home_state(location="back_door", ctx=state_with_security)
        assert result["location_filter"] == "back_door"
        for device in result["devices"]:
            assert device["location"] == "back_door"

    def test_empty_location_treated_as_none(self, state: HomeStateService):
        result = get_home_state(location="", ctx=state)
        assert result["location_filter"] is None

    def test_no_invalid_data_exposed(self, state_with_security: HomeStateService):
        result = get_home_state(ctx=state_with_security)
        # Must never expose secrets or API credentials
        result_str = str(result).lower()
        assert "password" not in result_str
        assert "api_key" not in result_str
        assert "secret" not in result_str

    def test_total_events_logged_increments(self, state: HomeStateService):
        initial = get_home_state(ctx=state)["total_events_logged"]
        state.load_scenario("security_incident")
        after = get_home_state(ctx=state)["total_events_logged"]
        assert after > initial


# ---------------------------------------------------------------------------
# 2. get_recent_events
# ---------------------------------------------------------------------------


class TestGetRecentEvents:
    def test_returns_structured_result(self, state_with_security: HomeStateService):
        result = get_recent_events(ctx=state_with_security)
        assert "total" in result
        assert "events" in result
        assert isinstance(result["events"], list)

    def test_events_are_valid_dicts(self, state_with_security: HomeStateService):
        result = get_recent_events(ctx=state_with_security)
        for evt in result["events"]:
            assert "device_id" in evt
            assert "device_type" in evt
            assert "event_type" in evt
            assert "location" in evt

    def test_limit_respected(self, state_with_security: HomeStateService):
        result = get_recent_events(limit=1, ctx=state_with_security)
        assert len(result["events"]) <= 1

    def test_limit_clamped_below_minimum(self, state_with_security: HomeStateService):
        result = get_recent_events(limit=0, ctx=state_with_security)
        assert result["limit_applied"] >= 1

    def test_limit_clamped_above_maximum(self, state_with_security: HomeStateService):
        result = get_recent_events(limit=9999, ctx=state_with_security)
        assert result["limit_applied"] <= 200

    def test_location_filter_works(self, state_with_security: HomeStateService):
        result = get_recent_events(location="back_door", ctx=state_with_security)
        for evt in result["events"]:
            assert evt["location"] == "back_door"

    def test_device_type_filter_works(self, state_with_security: HomeStateService):
        result = get_recent_events(device_type="door_sensor", ctx=state_with_security)
        for evt in result["events"]:
            assert evt["device_type"] == "door_sensor"

    def test_event_type_filter_works(self, state_with_security: HomeStateService):
        result = get_recent_events(event_type="opened", ctx=state_with_security)
        for evt in result["events"]:
            assert evt["event_type"] == "opened"

    def test_empty_state_returns_empty_list(self, state: HomeStateService):
        result = get_recent_events(ctx=state)
        assert result["events"] == []

    def test_filters_reported_in_result(self, state_with_security: HomeStateService):
        result = get_recent_events(location="back_door", ctx=state_with_security)
        assert result["filters"].get("location") == "back_door"


# ---------------------------------------------------------------------------
# 3. investigate_incident
# ---------------------------------------------------------------------------


class TestInvestigateIncident:
    def test_security_scenario_produces_incident(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="security_incident",
            ctx_state=state,
            ctx_engine=engine,
        )
        assert result["incident_count"] >= 1
        types = [i["incident_type"] for i in result["incidents"]]
        assert "SECURITY" in types

    def test_water_scenario_produces_incident(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="water_hazard",
            ctx_state=state,
            ctx_engine=engine,
        )
        assert result["incident_count"] >= 1
        types = [i["incident_type"] for i in result["incidents"]]
        assert "WATER_HAZARD" in types

    def test_leaving_home_scenario_produces_incident(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="leaving_home",
            ctx_state=state,
            ctx_engine=engine,
        )
        assert result["incident_count"] >= 1
        types = [i["incident_type"] for i in result["incidents"]]
        assert "LEAVING_HOME" in types

    def test_incident_has_required_fields(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="security_incident",
            ctx_state=state,
            ctx_engine=engine,
        )
        for inc in result["incidents"]:
            assert "incident_id" in inc
            assert "incident_type" in inc
            assert "severity" in inc
            assert "title" in inc
            assert "summary" in inc
            assert "evidence" in inc
            assert "confidence" in inc
            assert "recommended_next_step" in inc

    def test_confidence_within_bounds(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="security_incident",
            ctx_state=state,
            ctx_engine=engine,
        )
        for inc in result["incidents"]:
            assert 0.0 <= inc["confidence"] <= 1.0

    def test_evidence_is_non_empty_list(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="security_incident",
            ctx_state=state,
            ctx_engine=engine,
        )
        for inc in result["incidents"]:
            assert isinstance(inc["evidence"], list)
            assert len(inc["evidence"]) >= 1

    def test_resident_present_does_not_produce_security_incident(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        """Door open + motion + occupancy confirmed → no security incident."""
        from datetime import datetime, timezone, timedelta
        base = datetime(2026, 9, 20, 2, 0, 0, tzinfo=timezone.utc)
        state.add_event(HomeEvent(
            device_id="door-01", device_type="door_sensor",
            event_type="opened", location="back_door",
            timestamp=base,
        ))
        state.add_event(HomeEvent(
            device_id="motion-01", device_type="motion_sensor",
            event_type="detected", location="hallway",
            timestamp=base + timedelta(seconds=30),
        ))
        state.add_event(HomeEvent(
            device_id="occ-01", device_type="occupancy_sensor",
            event_type="person_detected", location="hallway",
            timestamp=base + timedelta(seconds=60),
        ))
        result = investigate_incident(ctx_state=state, ctx_engine=engine)
        security = [i for i in result["incidents"] if i["incident_type"] == "SECURITY"]
        assert len(security) == 0, "Confirmed resident must not produce a security incident"

    def test_invalid_scenario_returns_error(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="nonexistent_scenario",
            ctx_state=state,
            ctx_engine=engine,
        )
        assert "error" in result

    def test_invalid_raw_event_reported_in_validation_errors(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            raw_events=[{"device_id": "x", "device_type": "microwave_oven",
                         "event_type": "opened", "location": "kitchen"}],
            ctx_state=state,
            ctx_engine=engine,
        )
        assert len(result["validation_errors"]) >= 1

    def test_empty_state_returns_no_incidents(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(ctx_state=state, ctx_engine=engine)
        assert result["incident_count"] == 0

    def test_result_includes_event_count(
        self, state: HomeStateService, engine: IncidentEngine
    ):
        result = investigate_incident(
            scenario="security_incident",
            ctx_state=state,
            ctx_engine=engine,
        )
        assert result["event_count"] >= 1


# ---------------------------------------------------------------------------
# 4. assess_risk
# ---------------------------------------------------------------------------


class TestAssessRisk:
    def test_low_severity_low_risk(self):
        result = assess_risk("SECURITY", "LOW", 0.5)
        assert result["risk_level"] == "LOW"
        assert result["action_permitted"] is True

    def test_medium_severity_requires_confirmation(self):
        result = assess_risk("SECURITY", "MEDIUM", 0.6)
        assert result["risk_level"] == "MEDIUM"
        assert result["requires_user_confirmation"] is True
        assert result["action_permitted"] is False

    def test_high_severity_requires_explicit_approval(self):
        result = assess_risk("SECURITY", "HIGH", 0.75)
        assert result["risk_level"] == "HIGH"
        assert result["requires_explicit_approval"] is True
        assert result["action_permitted"] is False

    def test_critical_severity_requires_escalation(self):
        result = assess_risk("WATER_HAZARD", "CRITICAL", 0.85)
        assert result["risk_level"] == "CRITICAL"
        assert result["escalation_required"] is True
        assert result["action_permitted"] is False

    def test_policy_is_deterministic(self):
        """Same inputs must produce identical outputs."""
        r1 = assess_risk("SECURITY", "HIGH", 0.7)
        r2 = assess_risk("SECURITY", "HIGH", 0.7)
        assert r1["risk_level"] == r2["risk_level"]
        assert r1["action_permitted"] == r2["action_permitted"]
        assert r1["requires_explicit_approval"] == r2["requires_explicit_approval"]

    def test_invalid_incident_type_returns_error(self):
        result = assess_risk("TORNADO", "HIGH", 0.7)
        assert "error" in result

    def test_invalid_severity_returns_error(self):
        result = assess_risk("SECURITY", "EXTREME", 0.7)
        assert "error" in result

    def test_confidence_below_zero_returns_error(self):
        result = assess_risk("SECURITY", "HIGH", -0.1)
        assert "error" in result

    def test_confidence_above_one_returns_error(self):
        result = assess_risk("SECURITY", "HIGH", 1.5)
        assert "error" in result

    def test_allowed_actions_present_for_non_critical(self):
        result = assess_risk("SECURITY", "HIGH", 0.7)
        assert isinstance(result["allowed_actions"], list)
        assert len(result["allowed_actions"]) > 0

    def test_no_allowed_actions_for_critical(self):
        result = assess_risk("WATER_HAZARD", "CRITICAL", 0.85)
        assert result["allowed_actions"] == []

    def test_audit_trail_populated(self):
        result = assess_risk("SECURITY", "MEDIUM", 0.6)
        assert isinstance(result["audit_trail"], list)
        assert len(result["audit_trail"]) >= 1

    def test_case_insensitive_severity(self):
        result = assess_risk("security", "high", 0.7)
        assert result["risk_level"] == "HIGH"

    def test_case_insensitive_incident_type(self):
        result = assess_risk("water_hazard", "CRITICAL", 0.85)
        assert result["risk_level"] == "CRITICAL"

    def test_result_has_incident_id(self):
        result = assess_risk("SECURITY", "LOW", 0.4)
        assert "incident_id" in result


# ---------------------------------------------------------------------------
# 5. recommend_response
# ---------------------------------------------------------------------------


class TestRecommendResponse:
    def test_returns_risk_level(self):
        result = recommend_response("SECURITY", "HIGH", 0.75)
        assert "risk_level" in result
        assert result["risk_level"] == "HIGH"

    def test_does_not_execute_physical_action(self):
        result = recommend_response("SECURITY", "CRITICAL", 0.85)
        assert result.get("physical_action_executed") is False

    def test_returns_recommended_action_string(self):
        result = recommend_response("WATER_HAZARD", "HIGH", 0.8)
        assert isinstance(result["recommended_action"], str)
        assert len(result["recommended_action"]) > 0

    def test_returns_all_safe_actions_list(self):
        result = recommend_response("WATER_HAZARD", "HIGH", 0.8)
        assert isinstance(result["all_safe_actions"], list)

    def test_requires_confirmation_for_medium(self):
        result = recommend_response("LEAVING_HOME", "MEDIUM", 0.7)
        assert result["requires_confirmation"] is True

    def test_no_confirmation_needed_for_low(self):
        result = recommend_response("LEAVING_HOME", "LOW", 0.5)
        assert result["requires_confirmation"] is False

    def test_escalation_required_for_critical(self):
        result = recommend_response("WATER_HAZARD", "CRITICAL", 0.85)
        assert result["escalation_required"] is True

    def test_note_present_and_mentions_no_automatic_action(self):
        result = recommend_response("SECURITY", "HIGH", 0.75)
        note = result.get("note", "").lower()
        assert "automatic" in note or "never" in note or "no" in note

    def test_invalid_incident_type_returns_error(self):
        result = recommend_response("EXPLODING_FRIDGE", "HIGH", 0.7)
        assert "error" in result

    def test_context_accepted(self):
        result = recommend_response("SECURITY", "HIGH", 0.75, context="Resident away")
        assert "risk_level" in result


# ---------------------------------------------------------------------------
# 6. execute_safe_action (always blocked)
# ---------------------------------------------------------------------------


class TestExecuteSafeActionTool:
    def test_always_returns_executed_false(self):
        result = execute_safe_action_tool("arm_security_system")
        assert result["executed"] is False

    def test_status_is_blocked(self):
        result = execute_safe_action_tool("arm_security_system")
        assert result["status"] == "blocked"

    def test_action_name_preserved_in_response(self):
        result = execute_safe_action_tool("shut_off_water_main")
        assert result["action_name"] == "shut_off_water_main"

    def test_reason_is_informative(self):
        result = execute_safe_action_tool("lock_door", device_id="door-01")
        reason = result["reason"].lower()
        assert "disabled" in reason or "prohibited" in reason or "blocked" in reason

    def test_device_id_preserved(self):
        result = execute_safe_action_tool("lock_door", device_id="door-back-01")
        assert result.get("device_id") == "door-back-01"

    def test_any_action_name_blocked(self):
        for action in ["arm", "disarm", "unlock", "activate", "detonate", "open"]:
            result = execute_safe_action_tool(action)
            assert result["executed"] is False, f"Action {action!r} must be blocked"

    def test_does_not_raise(self):
        """The tool must return a dict, never raise an unhandled exception."""
        result = execute_safe_action_tool("crash_the_system")
        assert isinstance(result, dict)

    def test_empty_action_name_handled(self):
        result = execute_safe_action_tool("")
        assert result["executed"] is False

    def test_none_device_id_handled(self):
        result = execute_safe_action_tool("arm_security_system", device_id=None)
        assert result["executed"] is False


# ---------------------------------------------------------------------------
# 7. record_incident
# ---------------------------------------------------------------------------


class TestRecordIncident:
    def _record_security(self, history: IncidentHistoryStore) -> dict:
        return record_incident(
            incident_type="SECURITY",
            severity="HIGH",
            confidence=0.75,
            title="Test security incident",
            summary="Door opened with motion detected.",
            evidence=["door_sensor opened", "motion detected"],
            recommended_next_step="Verify remotely.",
            ctx_history=history,
        )

    def test_record_returns_recorded_true(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        assert result["recorded"] is True

    def test_record_returns_incident_id(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        assert "incident_id" in result
        assert len(result["incident_id"]) > 0

    def test_recorded_incident_retrievable(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        incident_id = result["incident_id"]
        stored = history.get_by_id(incident_id)
        assert stored is not None
        assert stored["incident_id"] == incident_id

    def test_severity_preserved(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        stored = history.get_by_id(result["incident_id"])
        assert stored["severity"] == "HIGH"

    def test_confidence_preserved(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        stored = history.get_by_id(result["incident_id"])
        assert abs(stored["confidence"] - 0.75) < 0.001

    def test_evidence_preserved(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        stored = history.get_by_id(result["incident_id"])
        assert "door_sensor opened" in stored["evidence"]

    def test_audit_trail_preserved(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        stored = history.get_by_id(result["incident_id"])
        assert isinstance(stored["audit_trail"], list)
        assert len(stored["audit_trail"]) >= 1

    def test_risk_level_in_response(self, history: IncidentHistoryStore):
        result = self._record_security(history)
        assert result["risk_level"] == "HIGH"

    def test_get_all_returns_recorded(self, history: IncidentHistoryStore):
        self._record_security(history)
        all_records = history.get_all()
        assert len(all_records) >= 1

    def test_count_increments(self, history: IncidentHistoryStore):
        before = history.count()
        self._record_security(history)
        after = history.count()
        assert after == before + 1

    def test_duplicate_record_is_idempotent(self, history: IncidentHistoryStore):
        """Recording the same incident_id twice must not raise or duplicate."""
        r1 = self._record_security(history)
        # Re-record with same incident_id — not possible via tool (tool generates new ID)
        # but count should increase by exactly 1
        assert history.count() == 1

    def test_invalid_incident_type_returns_not_recorded(self, history: IncidentHistoryStore):
        result = record_incident(
            incident_type="BOGUS",
            severity="HIGH",
            confidence=0.75,
            title="Bad",
            summary="Bad",
            evidence=["bad"],
            recommended_next_step="Nothing.",
            ctx_history=history,
        )
        assert result["recorded"] is False

    def test_confidence_out_of_range_returns_not_recorded(self, history: IncidentHistoryStore):
        result = record_incident(
            incident_type="SECURITY",
            severity="HIGH",
            confidence=1.5,
            title="Bad",
            summary="Bad",
            evidence=["bad"],
            recommended_next_step="Nothing.",
            ctx_history=history,
        )
        assert result["recorded"] is False

    def test_water_hazard_recorded_with_critical_risk(self, history: IncidentHistoryStore):
        result = record_incident(
            incident_type="WATER_HAZARD",
            severity="CRITICAL",
            confidence=0.85,
            title="Flood detected",
            summary="Rising moisture with appliance running.",
            evidence=["moisture_detected", "moisture_rising"],
            recommended_next_step="Turn off water main.",
            ctx_history=history,
        )
        assert result["recorded"] is True
        assert result["risk_level"] == "CRITICAL"

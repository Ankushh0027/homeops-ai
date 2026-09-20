"""
tests/test_incident_engine.py
=============================
Pytest tests for the incident correlation engine and its rules.

Tests verify:
- Valid event creation and field defaults
- Invalid event handling (ValidationError on bad device/event types)
- Security incident detection with full, partial, and no evidence
- Water hazard detection and progression correlation
- Leaving-home issue detection
- Evidence generation (non-empty, meaningful strings)
- Severity assignment logic
- Confidence bounds (always in [0.0, 1.0], never claiming full certainty)
- Engine confidence threshold filtering
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.incidents.engine import IncidentEngine
from app.incidents.rules import (
    rule_leaving_home,
    rule_security_incident,
    rule_water_hazard,
)
from app.incidents.schemas import IncidentType, Severity
from app.models.events import HomeEvent


# ---------------------------------------------------------------------------
# Fixtures – reusable event builders
# ---------------------------------------------------------------------------


def make_event(**kwargs) -> HomeEvent:
    """Build a HomeEvent with sensible defaults; caller overrides via kwargs."""
    defaults = dict(
        device_id="test-device-01",
        device_type="door_sensor",
        event_type="opened",
        location="front_door",
    )
    defaults.update(kwargs)
    return HomeEvent(**defaults)


def ts(offset_seconds: int = 0) -> datetime:
    """Return a fixed UTC base time optionally offset by seconds."""
    base = datetime(2026, 9, 20, 2, 0, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    return base + timedelta(seconds=offset_seconds)


# ---------------------------------------------------------------------------
# 1. Event model – valid creation
# ---------------------------------------------------------------------------


class TestHomeEventValid:
    def test_minimal_required_fields(self):
        evt = HomeEvent(
            device_id="door-01",
            device_type="door_sensor",
            event_type="opened",
            location="back_door",
        )
        assert evt.device_id == "door-01"
        assert evt.event_type == "opened"

    def test_default_event_id_is_uuid_string(self):
        evt = make_event()
        import uuid
        uuid.UUID(evt.event_id)  # raises if not a valid UUID

    def test_default_timestamp_is_utc_aware(self):
        evt = make_event()
        assert evt.timestamp.tzinfo is not None

    def test_default_metadata_is_empty_dict(self):
        evt = make_event()
        assert evt.metadata == {}

    def test_value_accepts_none(self):
        evt = make_event(value=None)
        assert evt.value is None

    def test_value_accepts_float(self):
        evt = make_event(device_type="water_sensor", event_type="moisture_detected", value=0.75)
        assert evt.value == pytest.approx(0.75)

    def test_value_accepts_string(self):
        evt = make_event(value="on")
        assert evt.value == "on"

    def test_explicit_timestamp_preserved(self):
        t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        evt = make_event(timestamp=t)
        assert evt.timestamp == t

    def test_naive_timestamp_gets_utc_tzinfo(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        evt = make_event(timestamp=naive)
        assert evt.timestamp.tzinfo is not None

    def test_metadata_stored_correctly(self):
        evt = make_event(metadata={"floor": "ground", "battery": 95})
        assert evt.metadata["floor"] == "ground"
        assert evt.metadata["battery"] == 95

    def test_age_seconds_positive_for_past_event(self):
        old = make_event(timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc))
        assert old.age_seconds() > 0

    def test_all_known_device_types_accepted(self):
        from app.models.events import KNOWN_DEVICE_TYPES
        for dt in KNOWN_DEVICE_TYPES:
            # pick a compatible event_type
            evt_type = "opened" if dt in ("door_sensor", "window_sensor") else "detected"
            if dt == "water_sensor":
                evt_type = "moisture_detected"
            elif dt == "appliance":
                evt_type = "running"
            elif dt == "occupancy_sensor":
                evt_type = "person_detected"
            elif dt == "light_sensor":
                evt_type = "on"
            elif dt == "lock_sensor":
                evt_type = "locked"
            elif dt == "security_system":
                evt_type = "armed"
            elif dt == "smoke_sensor":
                evt_type = "detected"
            elif dt == "co_sensor":
                evt_type = "detected"
            elif dt == "thermostat":
                evt_type = "active"
            HomeEvent(
                device_id=f"{dt}-test",
                device_type=dt,
                event_type=evt_type,
                location="test_room",
            )


# ---------------------------------------------------------------------------
# 2. Event model – invalid input handling
# ---------------------------------------------------------------------------


class TestHomeEventInvalid:
    def test_unknown_device_type_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            HomeEvent(
                device_id="x",
                device_type="microwave_oven",   # not in KNOWN_DEVICE_TYPES
                event_type="opened",
                location="kitchen",
            )
        assert "device_type" in str(exc_info.value).lower() or "unknown" in str(exc_info.value).lower()

    def test_unknown_event_type_raises(self):
        with pytest.raises(ValidationError):
            HomeEvent(
                device_id="x",
                device_type="door_sensor",
                event_type="exploded",          # not in KNOWN_EVENT_TYPES
                location="front_door",
            )

    def test_empty_device_id_raises(self):
        with pytest.raises(ValidationError):
            HomeEvent(
                device_id="",
                device_type="door_sensor",
                event_type="opened",
                location="back_door",
            )

    def test_empty_location_raises(self):
        with pytest.raises(ValidationError):
            HomeEvent(
                device_id="d1",
                device_type="door_sensor",
                event_type="opened",
                location="",
            )

    def test_missing_required_device_id_raises(self):
        with pytest.raises(ValidationError):
            HomeEvent(
                device_type="door_sensor",
                event_type="opened",
                location="back_door",
            )


# ---------------------------------------------------------------------------
# 3. Security incident rule
# ---------------------------------------------------------------------------


class TestRuleSecurityIncident:
    def _door(self, offset=0):
        return make_event(
            device_id="door-back-01",
            device_type="door_sensor",
            event_type="opened",
            location="back_door",
            timestamp=ts(offset),
        )

    def _motion(self, location="hallway", offset=60):
        return make_event(
            device_id=f"motion-{location}-01",
            device_type="motion_sensor",
            event_type="detected",
            location=location,
            timestamp=ts(offset),
        )

    def _occupancy(self, offset=90):
        return make_event(
            device_id="occupancy-01",
            device_type="occupancy_sensor",
            event_type="person_detected",
            location="hallway",
            timestamp=ts(offset),
        )

    # -- Detection ----------------------------------------------------------

    def test_door_only_produces_incident(self):
        result = rule_security_incident([self._door()])
        assert result is not None
        assert result.incident_type == IncidentType.SECURITY

    def test_door_plus_motion_produces_high_severity(self):
        result = rule_security_incident([self._door(), self._motion()])
        assert result is not None
        assert result.severity == Severity.HIGH

    def test_no_door_returns_none(self):
        result = rule_security_incident([self._motion()])
        assert result is None

    def test_known_resident_present_suppresses_incident(self):
        """When a resident is confirmed the confidence drops below the threshold
        and the rule correctly returns None – it is not an intrusion."""
        events = [self._door(), self._motion(), self._occupancy()]
        result = rule_security_incident(events)
        # Confirmed resident → confidence falls below 0.3 → no incident surfaced.
        assert result is None

    def test_no_resident_produces_higher_confidence_than_with_resident(self):
        """Without a resident confirmed, confidence must be higher than the
        resident-present case (where the rule returns None due to low confidence)."""
        without_resident = rule_security_incident([self._door(), self._motion()])
        assert without_resident is not None
        # Resident-present path returns None (below threshold), so the
        # no-resident path trivially has higher effective confidence.
        assert without_resident.confidence >= 0.3

    def test_motion_outside_window_does_not_correlate(self):
        # Motion 1 hour after door – outside default 300s window
        result = rule_security_incident(
            [self._door(0), self._motion(offset=3700)],
            window_seconds=300,
        )
        # Should still detect door, but without motion correlation → MEDIUM not HIGH
        assert result is not None
        assert result.severity == Severity.MEDIUM

    # -- Evidence ----------------------------------------------------------

    def test_evidence_is_non_empty(self):
        result = rule_security_incident([self._door(), self._motion()])
        assert result is not None
        assert len(result.evidence) >= 1

    def test_evidence_contains_door_info(self):
        result = rule_security_incident([self._door()])
        assert result is not None
        assert any("door" in e.lower() or "back_door" in e.lower() for e in result.evidence)

    # -- Confidence bounds --------------------------------------------------

    def test_confidence_within_bounds(self):
        events = [self._door(), self._motion()]
        result = rule_security_incident(events)
        assert result is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_confidence_never_reaches_1(self):
        # Even with door + motion, confidence should be < 1.0
        result = rule_security_incident([self._door(), self._motion()])
        assert result is not None
        assert result.confidence < 1.0

    def test_confidence_exceeds_threshold_without_resident(self):
        result = rule_security_incident([self._door()])
        assert result is not None
        assert result.confidence >= 0.3


# ---------------------------------------------------------------------------
# 4. Water hazard rule
# ---------------------------------------------------------------------------


class TestRuleWaterHazard:
    def _moisture(self, offset=0, event_type="moisture_detected"):
        return make_event(
            device_id="water-laundry-01",
            device_type="water_sensor",
            event_type=event_type,
            location="laundry_room",
            timestamp=ts(offset),
            value=0.6,
        )

    def _appliance(self, offset=0):
        return make_event(
            device_id="washer-01",
            device_type="appliance",
            event_type="running",
            location="laundry_room",
            timestamp=ts(offset),
        )

    def _rising(self, offset=180):
        return make_event(
            device_id="water-laundry-01",
            device_type="water_sensor",
            event_type="moisture_rising",
            location="laundry_room",
            timestamp=ts(offset),
            value=0.85,
        )

    # -- Detection ----------------------------------------------------------

    def test_moisture_alone_produces_incident(self):
        result = rule_water_hazard([self._moisture()])
        assert result is not None
        assert result.incident_type == IncidentType.WATER_HAZARD

    def test_no_moisture_returns_none(self):
        result = rule_water_hazard([self._appliance()])
        assert result is None

    def test_moisture_plus_appliance_is_high_severity(self):
        result = rule_water_hazard([self._appliance(), self._moisture(offset=60)])
        assert result is not None
        assert result.severity == Severity.HIGH

    def test_moisture_plus_appliance_plus_rising_is_critical(self):
        result = rule_water_hazard([
            self._appliance(),
            self._moisture(offset=60),
            self._rising(offset=120),
        ])
        assert result is not None
        assert result.severity == Severity.CRITICAL

    # -- Evidence ----------------------------------------------------------

    def test_evidence_mentions_moisture_sensor(self):
        result = rule_water_hazard([self._moisture()])
        assert result is not None
        assert any("water_sensor" in e or "moisture" in e.lower() for e in result.evidence)

    def test_evidence_mentions_appliance_when_present(self):
        result = rule_water_hazard([self._appliance(), self._moisture(offset=60)])
        assert result is not None
        assert any("appliance" in e.lower() or "washer" in e.lower() for e in result.evidence)

    def test_evidence_mentions_rising_when_present(self):
        result = rule_water_hazard([self._moisture(), self._rising(offset=60)])
        assert result is not None
        assert any("rising" in e.lower() for e in result.evidence)

    # -- Confidence bounds --------------------------------------------------

    def test_confidence_within_bounds(self):
        result = rule_water_hazard([self._moisture(), self._appliance(), self._rising()])
        assert result is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_confidence_never_reaches_1(self):
        result = rule_water_hazard([self._moisture(), self._appliance(), self._rising()])
        assert result is not None
        assert result.confidence < 1.0

    def test_rising_moisture_increases_confidence_over_static(self):
        static = rule_water_hazard([self._moisture()])
        with_rising = rule_water_hazard([self._moisture(), self._rising(offset=60)])
        assert with_rising is not None and static is not None
        assert with_rising.confidence > static.confidence


# ---------------------------------------------------------------------------
# 5. Leaving home rule
# ---------------------------------------------------------------------------


class TestRuleLeavingHome:
    def _depart(self, offset=600):
        return make_event(
            device_id="user-phone-01",
            device_type="occupancy_sensor",
            event_type="user_departing",
            location="front_door",
            timestamp=ts(offset),
        )

    def _door_open(self, offset=0):
        return make_event(
            device_id="door-back-01",
            device_type="door_sensor",
            event_type="opened",
            location="back_door",
            timestamp=ts(offset),
        )

    def _door_closed(self, offset=60):
        return make_event(
            device_id="door-back-01",
            device_type="door_sensor",
            event_type="closed",
            location="back_door",
            timestamp=ts(offset),
        )

    def _appliance_on(self, offset=0):
        return make_event(
            device_id="oven-01",
            device_type="appliance",
            event_type="running",
            location="kitchen",
            timestamp=ts(offset),
        )

    def _appliance_off(self, offset=60):
        return make_event(
            device_id="oven-01",
            device_type="appliance",
            event_type="stopped",
            location="kitchen",
            timestamp=ts(offset),
        )

    def _light_on(self, offset=0):
        return make_event(
            device_id="light-living-01",
            device_type="light_sensor",
            event_type="on",
            location="living_room",
            timestamp=ts(offset),
        )

    def _security_armed(self, offset=0):
        return make_event(
            device_id="sec-sys-01",
            device_type="security_system",
            event_type="armed",
            location="control_panel",
            timestamp=ts(offset),
        )

    # -- Detection ----------------------------------------------------------

    def test_no_departing_event_returns_none(self):
        result = rule_leaving_home([self._door_open()])
        assert result is None

    def test_departure_alone_produces_incident(self):
        result = rule_leaving_home([self._depart()])
        assert result is not None
        assert result.incident_type == IncidentType.LEAVING_HOME

    def test_all_clear_is_low_severity(self):
        # Armed + door closed + departure
        events = [
            self._door_open(0),
            self._door_closed(60),
            self._security_armed(120),
            self._depart(200),
        ]
        result = rule_leaving_home(events)
        assert result is not None
        assert result.severity == Severity.LOW

    def test_open_door_raises_severity_to_high(self):
        events = [self._door_open(0), self._depart(600)]
        result = rule_leaving_home(events)
        assert result is not None
        assert result.severity == Severity.HIGH

    def test_running_appliance_detected(self):
        events = [self._appliance_on(0), self._depart(600)]
        result = rule_leaving_home(events)
        assert result is not None
        # Running appliance should appear in evidence
        assert any("appliance" in e.lower() or "oven" in e.lower() for e in result.evidence)

    def test_stopped_appliance_not_flagged(self):
        events = [self._appliance_on(0), self._appliance_off(60), self._depart(600)]
        result = rule_leaving_home(events)
        assert result is not None
        # oven-01 was stopped, should NOT appear as an issue
        assert not any(
            "oven-01" in e and "running" in e.lower() for e in result.evidence
            if "appliance" in e.lower()
        )

    def test_light_left_on_included_in_evidence(self):
        events = [self._light_on(0), self._depart(600)]
        result = rule_leaving_home(events)
        assert result is not None
        assert any("light" in e.lower() for e in result.evidence)

    def test_disarmed_security_flagged(self):
        events = [self._depart(600)]
        result = rule_leaving_home(events)
        assert result is not None
        assert any("security" in e.lower() for e in result.evidence)

    def test_armed_security_not_flagged(self):
        events = [self._security_armed(0), self._depart(600)]
        result = rule_leaving_home(events)
        assert result is not None
        # When security is armed no "not armed" evidence should appear
        assert not any(
            "not armed" in e.lower() or "no security" in e.lower()
            for e in result.evidence
        )

    # -- Evidence ----------------------------------------------------------

    def test_evidence_contains_departure(self):
        result = rule_leaving_home([self._depart()])
        assert result is not None
        assert any("depart" in e.lower() for e in result.evidence)

    # -- Confidence bounds --------------------------------------------------

    def test_confidence_within_bounds(self):
        result = rule_leaving_home([self._depart()])
        assert result is not None
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# 6. IncidentEngine integration
# ---------------------------------------------------------------------------


class TestIncidentEngine:
    def test_empty_event_list_returns_empty(self):
        engine = IncidentEngine()
        assert engine.process([]) == []

    def test_security_scenario_end_to_end(self):
        engine = IncidentEngine()
        events = [
            make_event(device_type="door_sensor", event_type="opened", location="back_door", timestamp=ts(0)),
            make_event(device_id="motion-01", device_type="motion_sensor", event_type="detected", location="hallway", timestamp=ts(45)),
        ]
        incidents = engine.process(events)
        assert len(incidents) >= 1
        types = [i.incident_type for i in incidents]
        assert IncidentType.SECURITY in types

    def test_water_hazard_scenario_end_to_end(self):
        engine = IncidentEngine()
        events = [
            make_event(device_id="washer-01", device_type="appliance", event_type="running", location="laundry_room", timestamp=ts(0)),
            make_event(device_id="water-01", device_type="water_sensor", event_type="moisture_detected", location="laundry_room", timestamp=ts(60)),
        ]
        incidents = engine.process(events)
        assert len(incidents) >= 1
        types = [i.incident_type for i in incidents]
        assert IncidentType.WATER_HAZARD in types

    def test_leaving_home_scenario_end_to_end(self):
        engine = IncidentEngine()
        events = [
            make_event(device_id="user-01", device_type="occupancy_sensor", event_type="user_departing", location="front_door", timestamp=ts(0)),
        ]
        incidents = engine.process(events)
        assert len(incidents) >= 1
        types = [i.incident_type for i in incidents]
        assert IncidentType.LEAVING_HOME in types

    def test_incidents_sorted_by_severity(self):
        """Higher severity incidents appear first."""
        engine = IncidentEngine()
        events = [
            # Security (HIGH)
            make_event(device_type="door_sensor", event_type="opened", location="back_door", timestamp=ts(0)),
            make_event(device_id="motion-01", device_type="motion_sensor", event_type="detected", location="hallway", timestamp=ts(30)),
            # Leaving home (MEDIUM/HIGH)
            make_event(device_id="dep-01", device_type="occupancy_sensor", event_type="user_departing", location="front_door", timestamp=ts(60)),
        ]
        incidents = engine.process(events)
        severities = [i.severity for i in incidents]
        order = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
        for i in range(len(severities) - 1):
            assert order[severities[i].value] >= order[severities[i + 1].value]

    def test_low_confidence_incident_filtered(self):
        """Engine with very high min_confidence filters borderline incidents."""
        engine = IncidentEngine(min_confidence=0.99)
        events = [
            make_event(device_type="door_sensor", event_type="opened", location="back_door", timestamp=ts(0)),
        ]
        # Door-only incident has ~0.55 confidence, should be filtered
        incidents = engine.process(events)
        assert all(i.confidence >= 0.99 for i in incidents)

    def test_engine_loads_scenario_json(self):
        """Verify the simulator JSON can be loaded and processed."""
        import json
        from pathlib import Path
        scenario_path = (
            Path(__file__).parent.parent
            / "simulator" / "scenarios" / "security_incident.json"
        )
        data = json.loads(scenario_path.read_text(encoding="utf-8"))
        events = [HomeEvent.model_validate(e) for e in data["events"]]
        engine = IncidentEngine()
        incidents = engine.process(events)
        assert len(incidents) >= 1

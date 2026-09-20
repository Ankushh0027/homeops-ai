"""
app/incidents/rules.py
======================
Deterministic correlation rules for each supported incident scenario.

Each rule is a pure function:

    rule_<scenario>(events, window_seconds) -> Optional[Incident]

Rules examine a list of ``HomeEvent`` objects, apply temporal and logical
conditions, and either return a correlated ``Incident`` or ``None`` if the
evidence threshold is not met.

Design decisions
----------------
* Rules are kept as module-level functions – no class hierarchy – so they are
  trivially testable in isolation and easy to audit.
* Confidence is computed explicitly from evidence signals, not from an opaque
  model.  Every increment to confidence must have a named reason.
* Rules never claim certainty: the maximum confidence from partial evidence is
  capped at 0.85.  Full certainty (1.0) is reserved for future hardware
  confirmation paths.
* Rules do NOT trigger physical actions.  They return information only.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app.incidents.schemas import Incident, IncidentType, Severity
from app.models.events import HomeEvent


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _events_of_type(
    events: list[HomeEvent],
    device_type: str,
    event_type: str,
) -> list[HomeEvent]:
    """Return all events matching the given device_type and event_type."""
    return [
        e for e in events if e.device_type == device_type and e.event_type == event_type
    ]


def _within_window(
    anchor: HomeEvent,
    candidate: HomeEvent,
    window_seconds: int,
) -> bool:
    """Return True if *candidate* occurred within *window_seconds* after *anchor*."""
    delta = candidate.timestamp - anchor.timestamp
    return timedelta(seconds=0) <= delta <= timedelta(seconds=window_seconds)


def _any_within_window(
    anchors: list[HomeEvent],
    candidates: list[HomeEvent],
    window_seconds: int,
) -> bool:
    """Return True if any candidate follows any anchor within the window."""
    for anchor in anchors:
        for candidate in candidates:
            if _within_window(anchor, candidate, window_seconds):
                return True
    return False


# ---------------------------------------------------------------------------
# Rule 1 – Security incident
# ---------------------------------------------------------------------------


def rule_security_incident(
    events: list[HomeEvent],
    window_seconds: int = 300,
) -> Optional[Incident]:
    """Detect a potential security incident.

    Trigger conditions (each adds to confidence):
    1. A door or window sensor reports ``opened``.
    2. A motion sensor fires within the correlation window after the door.
    3. No occupancy sensor confirms a recognised resident.

    Returns an ``Incident`` only if at least the door-open condition is met
    and confidence exceeds 0.3.
    """
    door_opens = _events_of_type(events, "door_sensor", "opened")
    window_opens = _events_of_type(events, "window_sensor", "opened")
    entry_events = door_opens + window_opens

    if not entry_events:
        return None

    motion_events = _events_of_type(events, "motion_sensor", "detected")
    occupancy_confirmed = _events_of_type(events, "occupancy_sensor", "person_detected")

    # ------------------------------------------------------------------ #
    # Confidence scoring                                                   #
    # ------------------------------------------------------------------ #
    confidence = 0.0
    evidence: list[str] = []
    severity = Severity.MEDIUM

    # Signal 1: door / window opened (mandatory)
    for e in entry_events:
        evidence.append(
            f"{e.device_type} '{e.device_id}' reported '{e.event_type}' "
            f"at {e.location} ({e.timestamp.isoformat()})"
        )
    confidence += 0.4

    # Signal 2: motion detected after entry
    motion_after_entry = _any_within_window(entry_events, motion_events, window_seconds)
    if motion_after_entry:
        for e in motion_events:
            evidence.append(
                f"motion_sensor '{e.device_id}' detected motion "
                f"at {e.location} ({e.timestamp.isoformat()})"
            )
        confidence += 0.3
        severity = Severity.HIGH

    # Signal 3: no recognised resident occupancy reduces confidence penalty
    if occupancy_confirmed:
        # A known resident was detected – downgrade this to a low-risk event.
        for e in occupancy_confirmed:
            evidence.append(
                f"occupancy_sensor '{e.device_id}' confirmed presence "
                f"at {e.location} – may be a resident ({e.timestamp.isoformat()})"
            )
        confidence = max(0.0, confidence - 0.4)
        severity = Severity.LOW
    else:
        # No resident confirmation – increase concern
        evidence.append(
            "No occupancy sensor confirmed a recognised resident during this window."
        )
        confidence += 0.15

    # Cap partial-evidence confidence
    confidence = min(confidence, 0.85)

    if confidence < 0.3:
        return None

    if severity == Severity.LOW:
        recommended = (
            "Low likelihood of intrusion – review camera footage if available "
            "and confirm a resident entered the property."
        )
    elif severity == Severity.MEDIUM:
        recommended = (
            "Unverified entry detected.  Check whether a resident opened the "
            "entry point.  Consider arming the security system."
        )
    else:
        recommended = (
            "Potential intruder detected.  Verify remotely via camera.  "
            "If confirmed, contact emergency services.  "
            "Do NOT enter the property until cleared."
        )

    return Incident(
        incident_type=IncidentType.SECURITY,
        severity=severity,
        title="Unverified Entry Detected",
        summary=(
            f"An entry point was opened and {'motion was' if motion_after_entry else 'motion was NOT'} "
            f"detected afterwards. "
            f"{'No' if not occupancy_confirmed else 'A'} resident presence was confirmed. "
            f"Confidence: {confidence:.0%}."
        ),
        evidence=evidence,
        confidence=round(confidence, 3),
        recommended_next_step=recommended,
    )


# ---------------------------------------------------------------------------
# Rule 2 – Water hazard
# ---------------------------------------------------------------------------


def rule_water_hazard(
    events: list[HomeEvent],
    window_seconds: int = 300,
) -> Optional[Incident]:
    """Detect a potential water leak or flooding hazard.

    Trigger conditions:
    1. A water/moisture sensor reports ``moisture_detected`` (mandatory).
    2. An appliance is running concurrently (increases confidence).
    3. Moisture is rising (escalates severity).
    """
    moisture_events = _events_of_type(events, "water_sensor", "moisture_detected")

    if not moisture_events:
        return None

    appliance_running = _events_of_type(events, "appliance", "running")
    moisture_rising = _events_of_type(events, "water_sensor", "moisture_rising")

    confidence = 0.0
    evidence: list[str] = []
    severity = Severity.MEDIUM

    # Signal 1: moisture detected (mandatory)
    for e in moisture_events:
        evidence.append(
            f"water_sensor '{e.device_id}' reported moisture at {e.location} "
            f"({e.timestamp.isoformat()})"
        )
    confidence += 0.5

    # Signal 2: appliance running (likely source)
    appliance_concurrent = _any_within_window(
        moisture_events, appliance_running, window_seconds
    ) or _any_within_window(appliance_running, moisture_events, window_seconds)

    if appliance_concurrent:
        for e in appliance_running:
            evidence.append(
                f"appliance '{e.device_id}' was running at {e.location} "
                f"({e.timestamp.isoformat()}) – potential water source"
            )
        confidence += 0.25
        severity = Severity.HIGH

    # Signal 3: moisture rising (escalate)
    if moisture_rising:
        for e in moisture_rising:
            evidence.append(
                f"water_sensor '{e.device_id}' reported RISING moisture at {e.location} "
                f"({e.timestamp.isoformat()}) – situation is worsening"
            )
        confidence += 0.2
        severity = Severity.CRITICAL

    confidence = min(confidence, 0.85)

    if severity == Severity.CRITICAL:
        recommended = (
            "Rising moisture detected.  Turn off the water main immediately if safe to do so.  "
            "Unplug electrical appliances near the affected area.  "
            "Contact a plumber urgently.  "
            "IMPORTANT: No autonomous action will be taken – human approval required."
        )
    elif severity == Severity.HIGH:
        recommended = (
            "Moisture detected near a running appliance.  "
            "Inspect the appliance for leaks.  "
            "Stop the appliance if safe.  Contact maintenance."
        )
    else:
        recommended = (
            "Moisture detected.  Inspect the area for the source.  "
            "Ensure no appliances are leaking."
        )

    return Incident(
        incident_type=IncidentType.WATER_HAZARD,
        severity=severity,
        title="Water / Moisture Hazard Detected",
        summary=(
            f"Moisture was detected at one or more sensors. "
            f"{'An appliance was running concurrently. ' if appliance_concurrent else ''}"
            f"{'Moisture levels are RISING. ' if moisture_rising else ''}"
            f"Confidence: {confidence:.0%}."
        ),
        evidence=evidence,
        confidence=round(confidence, 3),
        recommended_next_step=recommended,
    )


# ---------------------------------------------------------------------------
# Rule 3 – Leaving home
# ---------------------------------------------------------------------------


def rule_leaving_home(
    events: list[HomeEvent],
    window_seconds: int = 300,
) -> Optional[Incident]:
    """Inspect home state when the user indicates they are leaving.

    Trigger condition:
    * An event of type ``user_departing`` must be present.

    The rule then audits the remaining events for unresolved home risks and
    produces a structured incident summarising what needs attention.
    """
    departing_events = [e for e in events if e.event_type == "user_departing"]

    if not departing_events:
        return None

    evidence: list[str] = []
    issues: list[str] = []
    severity = Severity.LOW
    confidence = 0.9  # departure context is explicit; issues are observable facts

    evidence.append(
        f"User indicated departure ({departing_events[0].timestamp.isoformat()})."
    )

    # ---- Check: doors/windows left open --------------------------------- #
    doors_open = _events_of_type(events, "door_sensor", "opened")
    doors_closed = _events_of_type(events, "door_sensor", "closed")
    open_door_ids = {e.device_id for e in doors_open} - {e.device_id for e in doors_closed}
    for e in doors_open:
        if e.device_id in open_door_ids:
            issues.append(f"Door '{e.device_id}' at {e.location} is open.")
            evidence.append(f"door_sensor '{e.device_id}' at {e.location} was opened and not closed.")
            severity = Severity.HIGH

    windows_open = _events_of_type(events, "window_sensor", "opened")
    windows_closed = _events_of_type(events, "window_sensor", "closed")
    open_window_ids = {e.device_id for e in windows_open} - {e.device_id for e in windows_closed}
    for e in windows_open:
        if e.device_id in open_window_ids:
            issues.append(f"Window '{e.device_id}' at {e.location} is open.")
            evidence.append(f"window_sensor '{e.device_id}' at {e.location} was opened and not closed.")
            if severity < Severity.MEDIUM:
                severity = Severity.MEDIUM

    # ---- Check: appliances running -------------------------------------- #
    appliances_on = _events_of_type(events, "appliance", "running")
    appliances_off = _events_of_type(events, "appliance", "stopped")
    running_appliance_ids = {e.device_id for e in appliances_on} - {e.device_id for e in appliances_off}
    for e in appliances_on:
        if e.device_id in running_appliance_ids:
            issues.append(f"Appliance '{e.device_id}' at {e.location} is still running.")
            evidence.append(
                f"appliance '{e.device_id}' at {e.location} is running and was not stopped."
            )
            if severity < Severity.MEDIUM:
                severity = Severity.MEDIUM

    # ---- Check: lights left on ------------------------------------------ #
    lights_on = _events_of_type(events, "light_sensor", "on")
    lights_off = _events_of_type(events, "light_sensor", "off")
    on_light_ids = {e.device_id for e in lights_on} - {e.device_id for e in lights_off}
    for e in lights_on:
        if e.device_id in on_light_ids:
            issues.append(f"Light '{e.device_id}' at {e.location} is on.")
            evidence.append(f"light_sensor '{e.device_id}' at {e.location} was left on.")

    # ---- Check: security system armed ----------------------------------- #
    armed_events = _events_of_type(events, "security_system", "armed")
    disarmed_events = _events_of_type(events, "security_system", "disarmed")
    is_armed = bool(armed_events) and not bool(disarmed_events)
    if not is_armed:
        issues.append("Security system is NOT armed.")
        evidence.append("No security_system 'armed' event was detected before departure.")
        if severity < Severity.MEDIUM:
            severity = Severity.MEDIUM

    if not issues:
        issues_text = "No unresolved issues detected."
        recommended = "Home appears to be in a safe state. Safe travels!"
    else:
        issues_text = " | ".join(issues)
        recommended = (
            f"Before leaving, please address: {issues_text}  "
            "HomeOps cannot take automatic action – your explicit approval is required "
            "for any physical changes."
        )

    return Incident(
        incident_type=IncidentType.LEAVING_HOME,
        severity=severity,
        title="Leaving Home – Pre-Departure Check",
        summary=(
            f"User is departing. "
            f"{'Unresolved issues found: ' + issues_text if issues else 'No issues detected.'}"
        ),
        evidence=evidence,
        confidence=round(confidence, 3),
        recommended_next_step=recommended,
    )

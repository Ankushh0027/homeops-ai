"""
app/mcp/tools.py
================
HomeOps MCP tool handler functions.

Each function in this module is a thin adapter that:
  1. Validates and sanitises MCP-supplied inputs.
  2. Delegates to the deterministic application core
     (HomeStateService, IncidentEngine, SafetyPolicy, IncidentHistoryStore).
  3. Returns a structured, JSON-serialisable dict.

Rules enforced here
-------------------
* No business logic lives in this file.  All decisions come from the core.
* No physical device actions are ever initiated.
* Safety policy is always consulted before recommending a response.
* All inputs are validated before reaching the core.
* ``execute_safe_action`` always returns a structured ``blocked`` response.

The functions are registered on the MCPServer in ``server.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import ValidationError

from app.incidents.engine import IncidentEngine
from app.incidents.schemas import Incident, IncidentType, Severity
from app.models.events import HomeEvent
from app.safety.policy import (
    AutonomousActionForbiddenError,
    evaluate_policy,
    execute_safe_action as _core_execute_safe_action,
)
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input sanitisation helpers
# ---------------------------------------------------------------------------

_MAX_LIMIT = 200
_MIN_LIMIT = 1


def _safe_limit(value: Any, default: int = 50) -> int:
    """Clamp an untrusted limit value to a safe integer range."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(_MIN_LIMIT, min(v, _MAX_LIMIT))


def _safe_str(value: Any, max_len: int = 256) -> Optional[str]:
    """Return a sanitised string or None if input is empty/None."""
    if value is None:
        return None
    s = str(value).strip()[:max_len]
    return s if s else None


# ---------------------------------------------------------------------------
# Tool 1: get_home_state
# ---------------------------------------------------------------------------


def get_home_state(
    location: Optional[str] = None,
    *,
    ctx: HomeStateService,
) -> dict[str, Any]:
    """Return the current simulated home state.

    Parameters
    ----------
    location:
        Optional location label to filter the snapshot.
    ctx:
        HomeStateService instance (injected by server.py).
    """
    sanitised_location = _safe_str(location)
    state = ctx.get_home_state(location=sanitised_location)
    logger.debug("get_home_state called (location=%r)", sanitised_location)
    return state


# ---------------------------------------------------------------------------
# Tool 2: get_recent_events
# ---------------------------------------------------------------------------


def get_recent_events(
    limit: int = 50,
    location: Optional[str] = None,
    device_type: Optional[str] = None,
    event_type: Optional[str] = None,
    *,
    ctx: HomeStateService,
) -> dict[str, Any]:
    """Return recent home events.

    Parameters
    ----------
    limit:
        Maximum events to return [1–200].
    location, device_type, event_type:
        Optional filters.
    ctx:
        HomeStateService instance.
    """
    clamped_limit = _safe_limit(limit)
    sanitised = {
        "location": _safe_str(location),
        "device_type": _safe_str(device_type),
        "event_type": _safe_str(event_type),
    }
    events = ctx.get_recent_events(
        limit=clamped_limit,
        location=sanitised["location"],
        device_type=sanitised["device_type"],
        event_type=sanitised["event_type"],
    )
    return {
        "total": len(events),
        "limit_applied": clamped_limit,
        "filters": {k: v for k, v in sanitised.items() if v is not None},
        "events": [e.model_dump(mode="json") for e in events],
    }


# ---------------------------------------------------------------------------
# Tool 3: investigate_incident
# ---------------------------------------------------------------------------


def investigate_incident(
    scenario: Optional[str] = None,
    raw_events: Optional[list[dict[str, Any]]] = None,
    *,
    ctx_state: HomeStateService,
    ctx_engine: IncidentEngine,
) -> dict[str, Any]:
    """Run the deterministic incident engine and return correlated incidents.

    Parameters
    ----------
    scenario:
        Named simulator scenario to load first (e.g. 'security_incident').
        If omitted, uses whatever events are already in the home state log.
    raw_events:
        Optional list of raw event dicts to validate and inject before
        running the engine.  Validated via ``HomeEvent.model_validate``.
    ctx_state:
        HomeStateService instance.
    ctx_engine:
        IncidentEngine instance.
    """
    validation_errors: list[str] = []

    # Load a named scenario if requested
    if scenario is not None:
        sanitised_scenario = _safe_str(scenario, max_len=64)
        try:
            ctx_state.load_scenario(sanitised_scenario)  # type: ignore[arg-type]
        except ValueError as exc:
            return {"error": str(exc), "incidents": []}

    # Inject caller-supplied raw events (validated)
    if raw_events:
        if not isinstance(raw_events, list):
            return {"error": "raw_events must be a list of event dicts.", "incidents": []}
        for i, raw in enumerate(raw_events[:100]):  # cap at 100 injected events
            try:
                event = HomeEvent.model_validate(raw)
                ctx_state.add_event(event)
            except ValidationError as exc:
                validation_errors.append(f"Event[{i}]: {exc.error_count()} validation error(s).")
                logger.warning("Invalid event at index %d: %s", i, exc)

    events = ctx_state.get_all_events()
    incidents = ctx_engine.process(events)

    return {
        "event_count": len(events),
        "incident_count": len(incidents),
        "validation_errors": validation_errors,
        "incidents": [
            {
                "incident_id": inc.incident_id,
                "incident_type": inc.incident_type.value,
                "severity": inc.severity.value,
                "title": inc.title,
                "summary": inc.summary,
                "evidence": list(inc.evidence),
                "confidence": inc.confidence,
                "recommended_next_step": inc.recommended_next_step,
                "created_at": inc.created_at.isoformat(),
            }
            for inc in incidents
        ],
    }


# ---------------------------------------------------------------------------
# Tool 4: assess_risk
# ---------------------------------------------------------------------------


def assess_risk(
    incident_type: str,
    severity: str,
    confidence: float,
    title: str = "Incident",
    summary: str = "Risk assessment requested via MCP.",
    evidence: Optional[list[str]] = None,
    recommended_next_step: str = "Review incident details.",
) -> dict[str, Any]:
    """Evaluate the safety policy for a described incident.

    Parameters
    ----------
    incident_type:
        One of SECURITY, WATER_HAZARD, LEAVING_HOME, UNKNOWN.
    severity:
        One of LOW, MEDIUM, HIGH, CRITICAL.
    confidence:
        Float in [0.0, 1.0].
    title, summary, evidence, recommended_next_step:
        Incident description fields.
    """
    # Validate incident_type
    try:
        inc_type = IncidentType(incident_type.upper())
    except ValueError:
        return {
            "error": (
                f"Invalid incident_type {incident_type!r}. "
                f"Valid: {[e.value for e in IncidentType]}"
            )
        }

    # Validate severity
    try:
        sev = Severity(severity.upper())
    except ValueError:
        return {
            "error": (
                f"Invalid severity {severity!r}. "
                f"Valid: {[e.value for e in Severity]}"
            )
        }

    # Validate confidence
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return {"error": "confidence must be a float in [0.0, 1.0]."}
    if not (0.0 <= conf <= 1.0):
        return {"error": f"confidence {conf} is out of range [0.0, 1.0]."}

    safe_evidence = evidence if isinstance(evidence, list) and evidence else [
        f"Risk assessment requested for {inc_type.value} incident."
    ]
    # Sanitise evidence strings
    safe_evidence = [str(e)[:500] for e in safe_evidence[:50]]

    incident = Incident(
        incident_type=inc_type,
        severity=sev,
        confidence=conf,
        title=str(title)[:200],
        summary=str(summary)[:1000],
        evidence=safe_evidence,
        recommended_next_step=str(recommended_next_step)[:1000],
    )
    decision = evaluate_policy(incident)

    return {
        "incident_id": incident.incident_id,
        "risk_level": decision.risk_level.value,
        "action_permission": decision.action_permission.value,
        "action_permitted": decision.action_permitted,
        "requires_user_confirmation": decision.requires_user_confirmation,
        "requires_explicit_approval": decision.requires_explicit_approval,
        "escalation_required": decision.escalation_required,
        "allowed_actions": list(decision.allowed_actions),
        "policy_rationale": decision.policy_rationale,
        "audit_trail": list(decision.audit_trail),
    }


# ---------------------------------------------------------------------------
# Tool 5: recommend_response
# ---------------------------------------------------------------------------


def recommend_response(
    incident_type: str,
    severity: str,
    confidence: float,
    context: Optional[str] = None,
) -> dict[str, Any]:
    """Return a safe response recommendation for an incident.

    This is a recommendation ONLY.  It never executes a physical action.

    Parameters
    ----------
    incident_type:
        SECURITY | WATER_HAZARD | LEAVING_HOME | UNKNOWN
    severity:
        LOW | MEDIUM | HIGH | CRITICAL
    confidence:
        Float in [0.0, 1.0].
    context:
        Optional free-text context string (max 500 chars).
    """
    # Reuse assess_risk validation
    assessment = assess_risk(
        incident_type=incident_type,
        severity=severity,
        confidence=confidence,
        title="Response recommendation request",
        summary=f"Recommend response for {incident_type} at {severity} severity.",
        evidence=[f"Confidence: {confidence:.0%}. Context: {context or 'none'}."],
        recommended_next_step="Evaluate recommended actions.",
    )
    if "error" in assessment:
        return assessment

    risk_level = assessment["risk_level"]
    requires_confirmation = assessment["requires_user_confirmation"]
    allowed = assessment["allowed_actions"]

    # Choose a primary recommended action
    primary_action = allowed[0] if allowed else "Review the incident details with a human operator."

    return {
        "risk_level": risk_level,
        "requires_confirmation": requires_confirmation,
        "requires_explicit_approval": assessment["requires_explicit_approval"],
        "escalation_required": assessment["escalation_required"],
        "recommended_action": primary_action,
        "all_safe_actions": allowed,
        "reason": assessment["policy_rationale"],
        "physical_action_executed": False,
        "note": (
            "This is a recommendation only.  "
            "HomeOps will never execute a physical action automatically."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 6: execute_safe_action
# ---------------------------------------------------------------------------


def execute_safe_action_tool(
    action_name: str,
    device_id: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """MCP tool wrapper for the physical-action gateway.

    This tool exists so that future agent architectures have a well-defined
    action boundary.  In the MVP it ALWAYS returns a structured ``blocked``
    response.  The underlying ``AutonomousActionForbiddenError`` is caught
    here and converted into a safe JSON response rather than propagating as
    an unhandled exception.

    The response NEVER contains ``"executed": true``.
    """
    sanitised_name = _safe_str(action_name, max_len=128) or "unknown"
    sanitised_device = _safe_str(device_id, max_len=128)

    try:
        _core_execute_safe_action(sanitised_name, device_id=sanitised_device, **kwargs)
        # If the above does NOT raise (should never happen in MVP), block explicitly.
        return {
            "executed": False,
            "status": "blocked",
            "action_name": sanitised_name,
            "reason": (
                "Unexpected: execute_safe_action returned without raising. "
                "Physical action blocked by MCP tool layer as a safety backstop."
            ),
        }
    except AutonomousActionForbiddenError as exc:
        logger.warning(
            "execute_safe_action blocked for '%s': %s", sanitised_name, exc
        )
        return {
            "executed": False,
            "status": "blocked",
            "action_name": sanitised_name,
            "device_id": sanitised_device,
            "reason": (
                "Physical device execution is disabled in the current MVP. "
                "All physical actions require explicit human approval. "
                "This guard rail is intentional and must not be bypassed."
            ),
        }


# ---------------------------------------------------------------------------
# Tool 7: record_incident
# ---------------------------------------------------------------------------


def record_incident(
    incident_type: str,
    severity: str,
    confidence: float,
    title: str,
    summary: str,
    evidence: list[str],
    recommended_next_step: str,
    *,
    ctx_history: IncidentHistoryStore,
) -> dict[str, Any]:
    """Record an incident to the audit history store.

    Evaluates the safety policy for the incident before recording, so the
    stored record always includes the associated risk assessment.

    Parameters
    ----------
    incident_type, severity, confidence, title, summary,
    evidence, recommended_next_step:
        Incident fields (validated here before recording).
    ctx_history:
        IncidentHistoryStore instance (injected by server.py).
    """
    # Validate via assess_risk helper
    assessment = assess_risk(
        incident_type=incident_type,
        severity=severity,
        confidence=confidence,
        title=title,
        summary=summary,
        evidence=evidence,
        recommended_next_step=recommended_next_step,
    )
    if "error" in assessment:
        return {"recorded": False, "error": assessment["error"]}

    # Reconstruct Incident and SafetyDecision from the assessment
    try:
        inc_type = IncidentType(incident_type.upper())
        sev = Severity(severity.upper())
        conf = float(confidence)
        safe_evidence = evidence if isinstance(evidence, list) and evidence else [
            f"Incident recorded via MCP for {inc_type.value}."
        ]
        safe_evidence = [str(e)[:500] for e in safe_evidence[:50]]

        incident = Incident(
            incident_type=inc_type,
            severity=sev,
            confidence=conf,
            title=str(title)[:200],
            summary=str(summary)[:1000],
            evidence=safe_evidence,
            recommended_next_step=str(recommended_next_step)[:1000],
        )
        decision = evaluate_policy(incident)
        recorded_id = ctx_history.record(incident, decision)
    except Exception as exc:
        logger.error("Failed to record incident via MCP: %s", exc)
        return {"recorded": False, "error": str(exc)}

    return {
        "recorded": True,
        "incident_id": recorded_id,
        "severity": sev.value,
        "risk_level": assessment["risk_level"],
        "message": f"Incident {recorded_id} successfully recorded to audit history.",
    }

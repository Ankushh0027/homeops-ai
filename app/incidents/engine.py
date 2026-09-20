"""
app/incidents/engine.py
=======================
Incident correlation engine.

The engine is the single entry point for converting a list of raw home events
into a list of correlated incidents.  It delegates to the individual rule
functions in ``rules.py`` and filters results against the configured minimum
confidence threshold.

Design decisions
----------------
* The engine is stateless between calls.  Each call to ``process`` is
  independent, making it safe to use in concurrent contexts and easy to test.
* Rules are executed in priority order: security first (life-safety), then
  water hazard (property damage), then leaving-home (informational).
* Results below ``min_confidence`` are silently dropped.  This prevents
  spurious low-signal alerts from reaching the safety policy layer.
* The engine does NOT make LLM calls, does NOT trigger device actions, and
  does NOT communicate with external services.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.incidents.rules import (
    rule_leaving_home,
    rule_security_incident,
    rule_water_hazard,
)
from app.incidents.schemas import Incident
from app.models.events import HomeEvent

logger = logging.getLogger(__name__)


class IncidentEngine:
    """Deterministic incident correlation engine.

    Parameters
    ----------
    correlation_window_seconds:
        Maximum seconds between events that are still treated as correlated.
        Defaults to the value from application settings.
    min_confidence:
        Incidents with confidence below this threshold are discarded.
        Defaults to the value from application settings.
    """

    def __init__(
        self,
        correlation_window_seconds: Optional[int] = None,
        min_confidence: Optional[float] = None,
    ) -> None:
        self.correlation_window_seconds: int = (
            correlation_window_seconds
            if correlation_window_seconds is not None
            else settings.INCIDENT_CORRELATION_WINDOW_SECONDS
        )
        self.min_confidence: float = (
            min_confidence
            if min_confidence is not None
            else settings.INCIDENT_MIN_CONFIDENCE_THRESHOLD
        )

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def process(self, events: list[HomeEvent]) -> list[Incident]:
        """Correlate *events* into zero or more incidents.

        Parameters
        ----------
        events:
            Raw home events to analyse.  May be in any order; rules sort
            internally where ordering matters.

        Returns
        -------
        list[Incident]
            Correlated incidents ordered by descending severity then
            descending confidence.  Empty list when nothing is detected.
        """
        if not events:
            logger.debug("IncidentEngine.process called with empty event list.")
            return []

        logger.info(
            "Processing %d events (window=%ds, min_confidence=%.2f)",
            len(events),
            self.correlation_window_seconds,
            self.min_confidence,
        )

        # Sort events by timestamp so temporal rules can rely on ordering.
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # Execute rules in priority order.
        candidates: list[Optional[Incident]] = [
            rule_security_incident(sorted_events, self.correlation_window_seconds),
            rule_water_hazard(sorted_events, self.correlation_window_seconds),
            rule_leaving_home(sorted_events, self.correlation_window_seconds),
        ]

        # Filter: drop None results and low-confidence incidents.
        incidents: list[Incident] = []
        for candidate in candidates:
            if candidate is None:
                continue
            if candidate.confidence < self.min_confidence:
                logger.debug(
                    "Incident %r dropped: confidence %.3f < threshold %.3f",
                    candidate.incident_type.value,
                    candidate.confidence,
                    self.min_confidence,
                )
                continue
            incidents.append(candidate)

        # Sort: severity descending, then confidence descending.
        severity_order = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
        incidents.sort(
            key=lambda i: (severity_order[i.severity.value], i.confidence),
            reverse=True,
        )

        logger.info("Engine produced %d incident(s).", len(incidents))
        return incidents

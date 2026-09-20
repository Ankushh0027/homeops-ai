"""
app/incidents/schemas.py
========================
Typed schemas for incidents produced by the correlation engine.

Design decisions
----------------
* ``Severity`` and ``IncidentType`` are Python enums – switch statements and
  comparisons in rule and policy code are exhaustive and auditable.
* ``Incident`` is a frozen Pydantic model; incidents must not be mutated
  after creation.  Audit correctness requires immutability.
* ``confidence`` is constrained to [0.0, 1.0].  The engine must never claim
  certainty it does not have.
* ``evidence`` is a list of human-readable strings describing each correlated
  event that contributed to the incident.  This makes audit trails possible
  without a database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    """Ordered severity levels used throughout the system.

    String-valued so they serialise cleanly to JSON / logs.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    def __ge__(self, other: "Severity") -> bool:  # type: ignore[override]
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return order.index(self) >= order.index(other)

    def __gt__(self, other: "Severity") -> bool:  # type: ignore[override]
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return order.index(self) > order.index(other)

    def __le__(self, other: "Severity") -> bool:  # type: ignore[override]
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return order.index(self) <= order.index(other)

    def __lt__(self, other: "Severity") -> bool:  # type: ignore[override]
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return order.index(self) < order.index(other)


class IncidentType(str, Enum):
    """Supported incident categories for the MVP."""

    SECURITY = "SECURITY"
    WATER_HAZARD = "WATER_HAZARD"
    LEAVING_HOME = "LEAVING_HOME"
    UNKNOWN = "UNKNOWN"


class Incident(BaseModel):
    """An incident produced by correlating one or more home events.

    Incidents are immutable once created (``model_config`` frozen).
    """

    model_config = {"frozen": True}

    incident_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique incident identifier.",
    )
    incident_type: IncidentType = Field(
        ...,
        description="Category of the incident.",
    )
    severity: Severity = Field(
        ...,
        description="Risk severity assigned by the correlation rule.",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Short, human-readable incident title.",
    )
    summary: str = Field(
        ...,
        min_length=1,
        description="Narrative explanation of what was detected and why.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="List of contributing event descriptions (audit trail).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Engine confidence in the incident classification [0.0–1.0].",
    )
    recommended_next_step: str = Field(
        ...,
        min_length=1,
        description="Actionable recommendation for a human operator.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time at which this incident was created.",
    )

    @field_validator("evidence")
    @classmethod
    def evidence_not_empty(cls, v: list[str]) -> list[str]:
        # An incident with no evidence is a logic error – require at least one.
        if not v:
            raise ValueError("An incident must contain at least one evidence item.")
        return v

    def __repr__(self) -> str:
        return (
            f"Incident(type={self.incident_type.value}, "
            f"severity={self.severity.value}, "
            f"confidence={self.confidence:.2f}, "
            f"title={self.title!r})"
        )

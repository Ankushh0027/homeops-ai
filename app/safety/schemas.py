"""
app/safety/schemas.py
=====================
Typed schemas for safety policy decisions.

Design decisions
----------------
* ``RiskLevel`` mirrors ``Severity`` from incidents but is a separate enum.
  The safety layer must not import from incidents to avoid circular coupling.
  The mapping between Severity → RiskLevel is performed in ``policy.py``.
* ``SafetyDecision`` is a frozen, fully-structured record.  All decisions are
  loggable and auditable without additional instrumentation.
* ``allowed_actions`` enumerates the *predefined safe actions* that may be
  presented to a user for approval at HIGH risk.  These are informational
  suggestions only – HomeOps does NOT execute them automatically.
* ``audit_trail`` accumulates a time-stamped log of which policy rules
  fired and why, enabling human review after the fact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Risk level used by the safety policy evaluator."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionPermission(str, Enum):
    """What class of action is permitted at this risk level."""

    INFORMATIONAL_ONLY = "INFORMATIONAL_ONLY"
    REQUIRES_USER_CONFIRMATION = "REQUIRES_USER_CONFIRMATION"
    REQUIRES_EXPLICIT_APPROVAL = "REQUIRES_EXPLICIT_APPROVAL"
    NO_AUTONOMOUS_ACTION = "NO_AUTONOMOUS_ACTION"


class SafetyDecision(BaseModel):
    """A fully structured, immutable safety policy decision.

    This object is produced once per incident and must not be mutated.
    """

    model_config = {"frozen": True}

    risk_level: RiskLevel = Field(
        ...,
        description="Risk level determined from the incident severity.",
    )
    action_permission: ActionPermission = Field(
        ...,
        description="What class of action is permitted by policy.",
    )
    action_permitted: bool = Field(
        ...,
        description=(
            "True when an informational or safe response may be delivered "
            "without further approval."
        ),
    )
    requires_user_confirmation: bool = Field(
        ...,
        description="True when the user must confirm before any action proceeds.",
    )
    requires_explicit_approval: bool = Field(
        ...,
        description=(
            "True when an explicit, out-of-band approval is required before "
            "any physical action is presented to the user."
        ),
    )
    escalation_required: bool = Field(
        ...,
        description=(
            "True when the policy requires escalation to a human operator or "
            "emergency services rather than any automated response."
        ),
    )
    allowed_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Predefined, pre-approved informational suggestions that may be "
            "shown to the user.  These are NEVER executed automatically."
        ),
    )
    policy_rationale: str = Field(
        ...,
        description="Human-readable explanation of why this decision was reached.",
    )
    audit_trail: list[str] = Field(
        default_factory=list,
        description="Ordered list of policy rules that fired, with timestamps.",
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this decision was produced.",
    )

    def __repr__(self) -> str:
        return (
            f"SafetyDecision(risk={self.risk_level.value}, "
            f"permission={self.action_permission.value}, "
            f"permitted={self.action_permitted})"
        )

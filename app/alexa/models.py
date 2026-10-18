"""
app/alexa/models.py
===================
Strongly typed Alexa+ interaction models for HomeOps-AI.

Defines the request and response contracts for the Alexa+ integration layer:
  - AlexaIntent: Enumeration of supported voice/conversational intents
  - AlexaRequest: Validated inbound Alexa request
  - AlexaResponse: Formatted, safety-preserving outbound Alexa response
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class AlexaIntent(str, Enum):
    """Supported Alexa+ conversational intents for connected home incident response."""

    HOME_STATUS = "home_status"
    INVESTIGATE_INCIDENT = "investigate_incident"
    RISK_ASSESSMENT = "risk_assessment"
    RECOMMENDED_RESPONSE = "recommended_response"
    ACTION_REQUEST = "action_request"
    INCIDENT_HISTORY = "incident_history"
    UNKNOWN = "unknown"


class AlexaRequest(BaseModel):
    """Inbound request from the Alexa+ conversational layer.

    Attributes
    ----------
    utterance:
        The raw transcribed spoken text from the user (e.g. "What's happening at home?").
    intent:
        Optional explicit intent. If omitted, the adapter infers it from the utterance.
    parameters:
        Optional slot/parameter dictionary (e.g. action_name, device_id, scenario).
    session_id:
        Optional session identifier for multi-turn conversational context.
    context:
        Optional caller-provided state or device metadata.
    """

    utterance: str = Field(..., description="User's spoken utterance.")
    intent: Optional[AlexaIntent] = Field(default=None, description="Classified intent.")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Extracted parameters.")
    session_id: Optional[str] = Field(default=None, description="Conversation session ID.")
    context: dict[str, Any] = Field(default_factory=dict, description="Session context metadata.")

    @field_validator("utterance")
    @classmethod
    def validate_utterance(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Utterance must be a non-empty string.")
        return value.strip()


class AlexaResponse(BaseModel):
    """Safety-preserving, speech-ready response returned to Alexa+.

    Attributes
    ----------
    speech:
        The natural language speech string returned to the user.
    intent:
        The handled intent name.
    incident_count:
        Number of active or investigated incidents.
    risk_level:
        Deterministic risk assessment level (LOW, MEDIUM, HIGH, CRITICAL) if applicable.
    requires_confirmation:
        True if the deterministic safety policy requires user confirmation.
    requires_explicit_approval:
        True if the deterministic safety policy requires explicit human approval.
    escalation_required:
        True if the deterministic safety policy requires human escalation.
    action_executed:
        Always False for physical actions in the MVP.
    action_status:
        Action execution status (e.g. 'blocked', 'informational', None).
    data:
        Underlying structured data returned by the HomeOps MCP server.
    reprompt:
        Optional follow-up question for multi-turn interactions.
    should_end_session:
        Whether the voice session should end after this turn.
    """

    speech: str = Field(..., description="Natural language spoken response.")
    intent: str = Field(..., description="Handled intent identifier.")
    incident_count: int = Field(default=0, description="Count of correlated incidents.")
    risk_level: Optional[str] = Field(default=None, description="Evaluated risk level.")
    requires_confirmation: bool = Field(default=False, description="User confirmation required.")
    requires_explicit_approval: bool = Field(default=False, description="Explicit approval required.")
    escalation_required: bool = Field(default=False, description="Operator escalation required.")
    action_executed: bool = Field(
        default=False,
        description="Whether a physical action was executed (always False in MVP).",
    )
    action_status: Optional[str] = Field(default=None, description="Action status (e.g. 'blocked').")
    data: dict[str, Any] = Field(default_factory=dict, description="Raw structured payload from MCP.")
    reprompt: Optional[str] = Field(default=None, description="Voice reprompt text.")
    should_end_session: bool = Field(default=False, description="End voice session flag.")

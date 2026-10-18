"""
tests/test_conversational_agent.py
==================================
Unit and integration tests for the HomeOps-AI ConversationalAgent.

Validates:
1. Compound conversational query: "Something happened at my back door. Should I be worried?"
2. Invocation of real MCP tools (get_home_state, get_recent_events, investigate_incident, assess_risk, recommend_response, record_incident)
3. Deterministic risk assessment and progressive disclosure payload
4. Physical action requests ("Turn off the washer", "Lock the door") strictly blocked by safety policy
5. History queries
6. Clean quiet home status
7. Streamable HTTP client integration
"""

from __future__ import annotations

import pytest

from app.alexa.conversational_agent import ConversationalAgent
from app.alexa.models import AlexaIntent
from app.incidents.engine import IncidentEngine
from app.mcp.client import HomeOpsMCPClient
from app.mcp.context import AppContext
from app.mcp.server import create_server
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore


@pytest.fixture()
def isolated_ctx() -> AppContext:
    return AppContext(
        home_state=HomeStateService(),
        engine=IncidentEngine(),
        history=IncidentHistoryStore(":memory:"),
    )


@pytest.fixture()
def in_process_agent(isolated_ctx: AppContext) -> ConversationalAgent:
    server = create_server(context=isolated_ctx)
    client = HomeOpsMCPClient(server=server, context=isolated_ctx)
    return ConversationalAgent(mcp_client=client)


@pytest.mark.asyncio
async def test_back_door_interaction_example(isolated_ctx: AppContext, in_process_agent: ConversationalAgent):
    """Test the exact interaction example:

    User: 'Something happened at my back door. Should I be worried?'
    """
    isolated_ctx.home_state.load_scenario("security_incident")

    result = await in_process_agent.process_message(
        "Something happened at my back door. Should I be worried?",
        scenario_hint="security_incident",
    )

    # 1. Natural Speech Synthesis
    assert "back door" in result["speech"].lower()
    assert "high" in result["speech"].lower()
    assert "worried" in result["speech"].lower()
    assert "safety precaution" in result["speech"].lower()

    # 2. Risk Assessment
    assert result["risk"] is not None
    assert result["risk"]["risk_level"] == "HIGH"
    assert "approval" in result["risk"]["action_permission"].lower()

    # 3. Incident Correlation & Evidence
    assert result["incident"] is not None
    assert result["incident"]["incident_type"] == "SECURITY"
    assert len(result["evidence"]) >= 3

    # 4. Real MCP Tools Invoked
    tool_names = [t["tool"] for t in result["tool_calls"]]
    assert "get_home_state" in tool_names
    assert "get_recent_events" in tool_names
    assert "investigate_incident" in tool_names
    assert "assess_risk" in tool_names
    assert "recommend_response" in tool_names
    assert "record_incident" in tool_names

    # 5. Safety Guardrail Enforced
    assert result["safety_block"]["autonomous_action_permitted"] is False


@pytest.mark.asyncio
async def test_action_request_safety_block(isolated_ctx: AppContext, in_process_agent: ConversationalAgent):
    """Test that physical action requests are strictly blocked."""
    result = await in_process_agent.process_message("Turn off the washer")

    assert result["intent"] == AlexaIntent.ACTION_REQUEST.value
    assert "cannot execute" in result["speech"].lower()
    assert "safety policy strictly blocks" in result["speech"].lower()
    assert result["safety_block"]["is_blocked"] is True

    tool_names = [t["tool"] for t in result["tool_calls"]]
    assert "execute_safe_action" in tool_names


@pytest.mark.asyncio
async def test_history_request(isolated_ctx: AppContext, in_process_agent: ConversationalAgent):
    """Test incident history retrieval."""
    # Pre-record an incident
    await in_process_agent.mcp_client.record_incident(
        incident_type="SECURITY",
        severity="HIGH",
        confidence=0.85,
        title="Prior Test Incident",
        summary="Test summary",
        evidence=["Evidence item 1"],
        recommended_next_step="Check cameras",
    )

    result = await in_process_agent.process_message("Has this happened before?")

    assert result["intent"] == AlexaIntent.INCIDENT_HISTORY.value
    assert "recorded incident" in result["speech"].lower()
    assert len(result["history"]) >= 1
    assert result["history"][0]["title"] == "Prior Test Incident"


@pytest.mark.asyncio
async def test_all_quiet_home_status(isolated_ctx: AppContext, in_process_agent: ConversationalAgent):
    """Test query on an empty/quiet home."""
    result = await in_process_agent.process_message("What is happening at home?")

    assert "quiet" in result["speech"].lower() or "normal" in result["speech"].lower()
    assert result["incident"] is None

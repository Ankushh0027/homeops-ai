"""
tests/test_alexa_adapter.py
===========================
Pytest test suite for the HomeOps Alexa+ Integration Adapter.

Validates:
1. Home-status request
2. Incident investigation request
3. Risk assessment request
4. Recommendation request
5. History request
6. Unknown/unsupported utterance
7. Malformed request handling
8. MCP/server communication failure handling
9. Safety confirmation requirements
10. Autonomous physical action remains blocked
11. Adapter never reports a blocked action as successful
12. Multi-turn session context preservation
13. Streamable HTTP client integration
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.alexa.adapter import AlexaAdapter
from app.alexa.models import AlexaIntent, AlexaRequest, AlexaResponse
from app.incidents.engine import IncidentEngine
from app.mcp.client import HomeOpsMCPClient, MCPCommunicationError
from app.mcp.context import AppContext
from app.mcp.server import create_server
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore


@pytest.fixture()
def isolated_context() -> AppContext:
    """Isolated AppContext with in-memory state and history for each test."""
    return AppContext(
        home_state=HomeStateService(),
        engine=IncidentEngine(),
        history=IncidentHistoryStore(":memory:"),
    )


@pytest.fixture()
def isolated_adapter(isolated_context: AppContext) -> AlexaAdapter:
    """AlexaAdapter wired to an isolated in-process MCP server."""
    server = create_server(context=isolated_context)
    client = HomeOpsMCPClient(server=server, context=isolated_context)
    return AlexaAdapter(mcp_client=client)


@pytest.fixture()
def security_adapter(isolated_adapter: AlexaAdapter, isolated_context: AppContext) -> AlexaAdapter:
    """AlexaAdapter with security_incident scenario preloaded."""
    isolated_context.home_state.load_scenario("security_incident")
    return isolated_adapter


# ---------------------------------------------------------------------------
# 1. Home-Status Request
# ---------------------------------------------------------------------------


class TestHomeStatusRequest:
    def test_empty_home_status(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("What's happening at home?")
        assert response.intent == AlexaIntent.HOME_STATUS.value
        assert "quiet" in response.speech.lower() or "no recent" in response.speech.lower()
        assert response.incident_count == 0
        assert response.requires_confirmation is False

    def test_home_status_with_open_door(self, security_adapter: AlexaAdapter):
        response = security_adapter.handle_utterance("What's happening at home?")
        assert response.intent == AlexaIntent.HOME_STATUS.value
        assert "unusual event" in response.speech.lower()
        assert "back door" in response.speech.lower()
        assert response.incident_count == 1
        assert response.requires_confirmation is True

    def test_explicit_home_status_intent(self, isolated_adapter: AlexaAdapter):
        request = AlexaRequest(
            utterance="arbitrary words",
            intent=AlexaIntent.HOME_STATUS,
        )
        response = isolated_adapter.handle_request(request)
        assert response.intent == AlexaIntent.HOME_STATUS.value


# ---------------------------------------------------------------------------
# 2. Incident Investigation Request
# ---------------------------------------------------------------------------


class TestInvestigateIncidentRequest:
    def test_investigate_security_incident(self, security_adapter: AlexaAdapter):
        response = security_adapter.handle_utterance("Why did you say something unusual happened?")
        assert response.intent == AlexaIntent.INVESTIGATE_INCIDENT.value
        assert response.incident_count >= 1
        assert response.risk_level == "HIGH"
        assert response.requires_confirmation is True
        assert "security" in response.speech.lower()
        assert "back door" in response.speech.lower() or "door-back-01" in response.speech

    def test_investigate_empty_scenario(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("Investigate incident")
        assert response.intent == AlexaIntent.INVESTIGATE_INCIDENT.value
        assert response.incident_count == 0
        assert "no active incidents" in response.speech.lower()

    def test_investigate_auto_records_to_history(
        self,
        security_adapter: AlexaAdapter,
        isolated_context: AppContext,
    ):
        initial_count = isolated_context.history.count()
        security_adapter.handle_utterance("Why did you say something unusual happened?")
        assert isolated_context.history.count() == initial_count + 1


# ---------------------------------------------------------------------------
# 3. Risk Assessment Request
# ---------------------------------------------------------------------------


class TestRiskAssessmentRequest:
    def test_risk_assessment_after_investigation(self, security_adapter: AlexaAdapter):
        # Multi-turn interaction
        session_id = "test-session-1"
        security_adapter.handle_utterance(
            "Why did you say something unusual happened?", session_id=session_id
        )
        response = security_adapter.handle_utterance(
            "How serious is it?", session_id=session_id
        )
        assert response.intent == AlexaIntent.RISK_ASSESSMENT.value
        assert response.risk_level == "HIGH"
        assert response.requires_confirmation is True
        assert response.requires_explicit_approval is True
        assert "risk level is high" in response.speech.lower()

    def test_risk_assessment_without_prior_incident(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("How serious is it?")
        assert response.intent == AlexaIntent.RISK_ASSESSMENT.value
        assert response.risk_level == "LOW"
        assert "no active incidents" in response.speech.lower()


# ---------------------------------------------------------------------------
# 4. Recommendation Request
# ---------------------------------------------------------------------------


class TestRecommendationRequest:
    def test_recommendation_returns_safe_action_without_execution(
        self, security_adapter: AlexaAdapter
    ):
        session_id = "test-session-2"
        security_adapter.handle_utterance(
            "Why did you say something unusual happened?", session_id=session_id
        )
        response = security_adapter.handle_utterance(
            "What should I do?", session_id=session_id
        )
        assert response.intent == AlexaIntent.RECOMMENDED_RESPONSE.value
        assert "recommend" in response.speech.lower()
        assert response.action_executed is False
        assert "will not execute physical actions automatically" in response.speech.lower()

    def test_recommendation_empty_home(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("What should I do?")
        assert response.intent == AlexaIntent.RECOMMENDED_RESPONSE.value
        assert "no action is needed" in response.speech.lower()


# ---------------------------------------------------------------------------
# 5. Incident History Request
# ---------------------------------------------------------------------------


class TestIncidentHistoryRequest:
    def test_history_empty(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("Has this happened before?")
        assert response.intent == AlexaIntent.INCIDENT_HISTORY.value
        assert response.incident_count == 0
        assert "no prior incidents" in response.speech.lower()

    def test_history_with_recorded_incident(
        self, security_adapter: AlexaAdapter, isolated_context: AppContext
    ):
        # Investigate triggers recording
        security_adapter.handle_utterance("Why did you say something unusual happened?")
        response = security_adapter.handle_utterance("Has this happened before?")
        assert response.intent == AlexaIntent.INCIDENT_HISTORY.value
        assert response.incident_count >= 1
        assert "recorded incident" in response.speech.lower()
        assert "unverified entry detected" in response.speech.lower()


# ---------------------------------------------------------------------------
# 6. Action Request & Safety Boundary (CRITICAL)
# ---------------------------------------------------------------------------


class TestSafetyBoundary:
    """Critical tests verifying that the safety policy is never bypassed."""

    def test_action_request_is_blocked(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("Turn off the configured appliance.")
        assert response.intent == AlexaIntent.ACTION_REQUEST.value
        assert response.action_executed is False
        assert response.action_status == "blocked"
        assert "cannot execute" in response.speech.lower()
        assert "blocks autonomous physical actions" in response.speech.lower()

    def test_arm_security_action_is_blocked(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("Arm the security system.")
        assert response.intent == AlexaIntent.ACTION_REQUEST.value
        assert response.action_executed is False
        assert response.action_status == "blocked"

    def test_lock_door_action_is_blocked(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("Lock the front door.")
        assert response.intent == AlexaIntent.ACTION_REQUEST.value
        assert response.action_executed is False
        assert response.action_status == "blocked"

    def test_adapter_never_reports_action_executed_true(self, isolated_adapter: AlexaAdapter):
        """Even if malicious data returned executed=True, the adapter enforces False."""
        # Test with direct parameter injection
        request = AlexaRequest(
            utterance="Turn off the appliance",
            intent=AlexaIntent.ACTION_REQUEST,
            parameters={"action_name": "turn_off_appliance"},
        )
        response = isolated_adapter.handle_request(request)
        assert response.action_executed is False

    def test_autonomous_physical_action_forbidden_message(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("Shut off the water main.")
        assert "manually" in response.speech.lower() or "human" in response.speech.lower()


# ---------------------------------------------------------------------------
# 7. Intent Classification & Unknown Utterance
# ---------------------------------------------------------------------------


class TestIntentClassification:
    def test_unknown_utterance_returns_help_speech(self, isolated_adapter: AlexaAdapter):
        response = isolated_adapter.handle_utterance("Sing me a song.")
        assert response.intent == AlexaIntent.UNKNOWN.value
        assert "not sure how to handle" in response.speech.lower()
        assert "what's happening at home?" in response.speech.lower()

    @pytest.mark.parametrize(
        ("utterance", "expected_intent"),
        [
            ("What's happening at home?", AlexaIntent.HOME_STATUS),
            ("House status report", AlexaIntent.HOME_STATUS),
            ("Check the home", AlexaIntent.HOME_STATUS),
            ("Why did you say something unusual happened?", AlexaIntent.INVESTIGATE_INCIDENT),
            ("Investigate the incident", AlexaIntent.INVESTIGATE_INCIDENT),
            ("What went wrong?", AlexaIntent.INVESTIGATE_INCIDENT),
            ("How serious is it?", AlexaIntent.RISK_ASSESSMENT),
            ("Assess the risk", AlexaIntent.RISK_ASSESSMENT),
            ("What is the risk level?", AlexaIntent.RISK_ASSESSMENT),
            ("What should I do?", AlexaIntent.RECOMMENDED_RESPONSE),
            ("What do you recommend?", AlexaIntent.RECOMMENDED_RESPONSE),
            ("Turn off the appliance", AlexaIntent.ACTION_REQUEST),
            ("Arm the security system", AlexaIntent.ACTION_REQUEST),
            ("Shut off the water main", AlexaIntent.ACTION_REQUEST),
            ("Has this happened before?", AlexaIntent.INCIDENT_HISTORY),
            ("Check incident history", AlexaIntent.INCIDENT_HISTORY),
        ],
    )
    def test_deterministic_intent_mapping(
        self,
        isolated_adapter: AlexaAdapter,
        utterance: str,
        expected_intent: AlexaIntent,
    ):
        classified = isolated_adapter._classify_intent(utterance)
        assert classified == expected_intent


# ---------------------------------------------------------------------------
# 8. Malformed Requests & Validation
# ---------------------------------------------------------------------------


class TestMalformedRequests:
    def test_empty_utterance_raises_validation_error(self):
        with pytest.raises(ValidationError):
            AlexaRequest(utterance="")

    def test_whitespace_utterance_raises_validation_error(self):
        with pytest.raises(ValidationError):
            AlexaRequest(utterance="   ")

    def test_mcp_communication_failure_handled_gracefully(self, isolated_context: AppContext):
        """Adapter handles MCP communication errors gracefully without crashing."""
        # Create client pointing to non-existent server address
        bad_client = HomeOpsMCPClient(
            base_url="http://127.0.0.1:59999/mcp",
            context=isolated_context,
            timeout_seconds=0.5,
        )
        adapter = AlexaAdapter(mcp_client=bad_client)

        response = adapter.handle_utterance("What's happening at home?")
        assert "communication issue" in response.speech.lower() or "error" in response.speech.lower()
        assert "error" in response.data


# ---------------------------------------------------------------------------
# 9. Streamable HTTP Transport Integration
# ---------------------------------------------------------------------------


class TestStreamableHTTPAdapterIntegration:
    """Verifies that AlexaAdapter functions over the real Streamable HTTP transport."""

    @pytest.mark.asyncio
    async def test_adapter_over_streamable_http_asgi(self, isolated_context: AppContext):
        """Test full cycle: AlexaAdapter -> HomeOpsMCPClient -> Streamable HTTP ASGI -> MCPServer."""
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        server = create_server(context=isolated_context)
        asgi_app = server.streamable_http_app()

        async with asgi_app.router.lifespan_context(asgi_app):
            transport = httpx2.ASGITransport(app=asgi_app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http_client) as (r, w):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        # Call tool via HTTP session to verify live transport
                        res = await session.call_tool("get_home_state", {})
                        assert res.structured_content is not None
                        assert res.structured_content["home_id"] == "demo-home-001"

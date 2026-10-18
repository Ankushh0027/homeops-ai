"""
tests/test_alexa_simulator.py
=============================
Pytest test suite for the HomeOps Alexa+ Simulator and Demo Runner.

Validates:
1. Simulator initialization and scenario preloading
2. Simulator uses real backend services rather than hard-coded strings
3. Scenario switching alters simulator responses dynamically
4. Deterministic 11-step hackathon demo execution
5. Safety boundary enforcement during simulation
6. Incident recording and history audit during simulation
"""

from __future__ import annotations

import pytest

from app.alexa.adapter import AlexaAdapter
from app.alexa.models import AlexaIntent
from app.alexa.simulator import AlexaSimulator
from app.incidents.engine import IncidentEngine
from app.mcp.client import HomeOpsMCPClient
from app.mcp.context import AppContext
from app.mcp.server import create_server
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore


@pytest.fixture()
def isolated_simulator() -> AlexaSimulator:
    """Creates a fresh, isolated AlexaSimulator with in-memory stores."""
    ctx = AppContext(
        home_state=HomeStateService(),
        engine=IncidentEngine(),
        history=IncidentHistoryStore(":memory:"),
    )
    server = create_server(context=ctx)
    client = HomeOpsMCPClient(server=server, context=ctx)
    adapter = AlexaAdapter(mcp_client=client)
    return AlexaSimulator(adapter=adapter, scenario="security_incident")


class TestAlexaSimulatorInitialization:
    def test_default_scenario_loaded(self, isolated_simulator: AlexaSimulator):
        assert isolated_simulator.scenario == "security_incident"
        ctx = isolated_simulator.adapter.mcp_client._context
        assert len(ctx.home_state.get_all_events()) == 3

    def test_switch_scenario_to_water_hazard(self, isolated_simulator: AlexaSimulator):
        count = isolated_simulator.load_scenario("water_hazard")
        assert count == 3
        # Asking home status should now reflect water sensor/dishwasher
        res = isolated_simulator.ask("What's happening at home?")
        assert res.intent == AlexaIntent.HOME_STATUS.value
        assert "water" in res.speech.lower() or "dishwasher" in res.speech.lower() or "kitchen" in res.speech.lower()


class TestSimulatorBackendIntegration:
    """Verifies that simulator uses the real backend engine and services."""

    def test_simulator_ask_security_incident_explanation(self, isolated_simulator: AlexaSimulator):
        res = isolated_simulator.ask("Why did you say something unusual happened?")
        assert res.intent == AlexaIntent.INVESTIGATE_INCIDENT.value
        assert res.incident_count >= 1
        assert res.risk_level == "HIGH"
        # Speech reflects dynamic backend evidence
        assert "back_door" in res.speech or "back door" in res.speech.lower()
        assert "hallway" in res.speech.lower()

    def test_simulator_ask_risk_assessment(self, isolated_simulator: AlexaSimulator):
        # Investigate first
        isolated_simulator.ask("Why did you say something unusual happened?")
        res = isolated_simulator.ask("How serious is it?")
        assert res.intent == AlexaIntent.RISK_ASSESSMENT.value
        assert res.risk_level == "HIGH"
        assert res.requires_confirmation is True
        assert res.requires_explicit_approval is True

    def test_simulator_ask_action_request_blocked(self, isolated_simulator: AlexaSimulator):
        res = isolated_simulator.ask("Turn off the configured appliance.")
        assert res.intent == AlexaIntent.ACTION_REQUEST.value
        assert res.action_executed is False
        assert res.action_status == "blocked"
        assert "cannot execute" in res.speech.lower()


class TestSimulatorDemoRunner:
    """Tests the deterministic 11-step hackathon demo scenario."""

    def test_run_demo_executes_all_steps(self, isolated_simulator: AlexaSimulator):
        responses = isolated_simulator.run_demo()
        # 6 user interaction turns in the 11-step demo
        assert len(responses) == 6

        # Step 5: home status
        assert responses[0].intent == AlexaIntent.HOME_STATUS.value
        assert responses[0].requires_confirmation is True

        # Step 6: explain incident
        assert responses[1].intent == AlexaIntent.INVESTIGATE_INCIDENT.value
        assert responses[1].risk_level == "HIGH"

        # Step 7: risk assessment
        assert responses[2].intent == AlexaIntent.RISK_ASSESSMENT.value
        assert responses[2].risk_level == "HIGH"
        assert responses[2].requires_explicit_approval is True

        # Step 8: recommended response
        assert responses[3].intent == AlexaIntent.RECOMMENDED_RESPONSE.value
        assert responses[3].action_executed is False

        # Step 9-10: physical action request
        assert responses[4].intent == AlexaIntent.ACTION_REQUEST.value
        assert responses[4].action_executed is False
        assert responses[4].action_status == "blocked"

        # Step 11: incident history verification
        assert responses[5].intent == AlexaIntent.INCIDENT_HISTORY.value
        assert responses[5].incident_count >= 1

    def test_demo_persists_incident_in_history(self, isolated_simulator: AlexaSimulator):
        ctx = isolated_simulator.adapter.mcp_client._context
        assert ctx.history.count() == 0
        isolated_simulator.run_demo()
        # Should now have 1 recorded incident in SQLite
        assert ctx.history.count() >= 1

"""
tests/test_indian_conversational_intelligence.py
================================================
Comprehensive tests for HomeOps-AI India-Aware Conversational Intelligence.

Validates:
1. Language detection: English, Hindi (Devanagari), and everyday Hinglish
2. 6-part structured response generation across languages
3. Exact Hinglish scenario: "Raat ko back door pe movement hui, kya karun?"
4. Hindi (Devanagari) scenario: "रात को बैक डोर पे हलचल हुई, क्या करूं?"
5. Multilingual physical action blocking ("Darwaza lock kar do", "दरवाजा लॉक करो")
6. Multilingual quiet home reporting ("Ghar safe hai kya?", "क्या सब ठीक है?")
7. Absence of fabricated data, fake numbers, or autonomous physical execution
"""

from __future__ import annotations

import pytest

from app.alexa.conversational_agent import ConversationalAgent
from app.alexa.conversational_synthesizer import ConversationalSynthesizer, LanguageDetector
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
def agent(isolated_ctx: AppContext) -> ConversationalAgent:
    server = create_server(context=isolated_ctx)
    client = HomeOpsMCPClient(server=server, context=isolated_ctx)
    return ConversationalAgent(mcp_client=client)


# ---------------------------------------------------------------------------
# Language Detection Tests
# ---------------------------------------------------------------------------

def test_language_detection_english():
    assert LanguageDetector.detect("Something happened at my back door. Should I be worried?") == "english"
    assert LanguageDetector.detect("Check for water hazards in the laundry room") == "english"
    assert LanguageDetector.detect("What is happening at home?") == "english"


def test_language_detection_hinglish():
    assert LanguageDetector.detect("Raat ko back door pe movement hui, kya karun?") == "hinglish"
    assert LanguageDetector.detect("Ghar safe hai kya?") == "hinglish"
    assert LanguageDetector.detect("Darwaza lock kar do please") == "hinglish"
    assert LanguageDetector.detect("Pani ka leak check karo") == "hinglish"
    assert LanguageDetector.detect("Main bahar ja raha hoon, ghar secure hai?") == "hinglish"


def test_language_detection_hindi():
    assert LanguageDetector.detect("रात को बैक डोर पे हलचल हुई, क्या करूं?") == "hindi"
    assert LanguageDetector.detect("क्या घर में सब ठीक है?") == "hindi"
    assert LanguageDetector.detect("दरवाजा लॉक कर दो") == "hindi"
    assert LanguageDetector.detect("पानी का रिसाव चेक करो") == "hindi"


# ---------------------------------------------------------------------------
# Hinglish 6-Part Structured Response Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hinglish_back_door_incident_response(isolated_ctx: AppContext, agent: ConversationalAgent):
    """Test Hinglish user query: 'Raat ko back door pe movement hui, kya karun?'"""
    isolated_ctx.home_state.load_scenario("security_incident")

    result = await agent.process_message(
        "Raat ko back door pe movement hui, kya karun?",
        scenario_hint="security_incident",
    )

    speech = result["speech"]
    assert result["language"] == "hinglish"
    assert result["incident"] is not None
    assert result["incident"]["incident_type"] == "SECURITY"
    assert result["risk"]["risk_level"] == "HIGH"

    # 1. Acknowledgment of concern
    assert "concern hona natural hai" in speech or "chinta" in speech

    # 2. Observed facts
    assert "back door" in speech.lower()
    assert "movement detect" in speech.lower() or "contact open" in speech.lower()

    # 3. Known vs uncertain
    assert "confirm nahi hai" in speech or "unverified" in speech.lower()

    # 4. Calibrated risk assessment matching engine
    assert "high risk" in speech.lower()

    # 5. Concrete safe next steps
    assert "safe jagah par" in speech.lower()
    assert "akele" in speech.lower()

    # 6. Explicit statement of what HomeOps has and has not done
    assert "lock nahi" in speech.lower()

    # Verify no fake emergency numbers were fabricated
    assert "100" not in speech
    assert "112" not in speech
    assert "police contacted" not in speech.lower()


# ---------------------------------------------------------------------------
# Hindi (Devanagari) 6-Part Structured Response Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hindi_back_door_incident_response(isolated_ctx: AppContext, agent: ConversationalAgent):
    """Test Hindi Devanagari query: 'रात को बैक डोर पे हलचल हुई, क्या करूं?'"""
    isolated_ctx.home_state.load_scenario("security_incident")

    result = await agent.process_message(
        "रात को बैक डोर पे हलचल हुई, क्या करूं?",
        scenario_hint="security_incident",
    )

    speech = result["speech"]
    assert result["language"] == "hindi"
    assert result["incident"] is not None
    assert result["risk"]["risk_level"] == "HIGH"

    # Check key components
    assert "चिंतित होना स्वाभाविक है" in speech
    assert "बैक डोर" in speech
    assert "प्रमाणित नहीं है" in speech or "अनिश्चित" in speech
    assert "HIGH" in speech or "जोखिम" in speech
    assert "सुरक्षित स्थान" in speech
    assert "स्वतः लॉक नहीं" in speech


# ---------------------------------------------------------------------------
# Action Request Blocking Across Languages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_block_hinglish(agent: ConversationalAgent):
    result = await agent.process_message("Darwaza lock kar do")
    assert result["intent"] == AlexaIntent.ACTION_REQUEST.value
    assert result["safety_block"]["is_blocked"] is True
    assert result["language"] == "hinglish"
    assert "autonomously" in result["speech"].lower()
    assert "strictly block" in result["speech"].lower() or "rok" in result["speech"].lower()


@pytest.mark.asyncio
async def test_action_block_hindi(agent: ConversationalAgent):
    result = await agent.process_message("दरवाजा लॉक करो")
    assert result["intent"] == AlexaIntent.ACTION_REQUEST.value
    assert result["safety_block"]["is_blocked"] is True
    assert result["language"] == "hindi"
    assert "स्वतः" in result["speech"]
    assert "प्रतिबंधित" in result["speech"]


# ---------------------------------------------------------------------------
# Quiet Home State Across Languages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quiet_home_hinglish(isolated_ctx: AppContext, agent: ConversationalAgent):
    isolated_ctx.home_state.clear()
    result = await agent.process_message("Ghar safe hai kya?")
    assert result["language"] == "hinglish"
    assert "normal" in result["speech"].lower() or "quiet" in result["speech"].lower()
    assert result["incident"] is None


@pytest.mark.asyncio
async def test_quiet_home_hindi(isolated_ctx: AppContext, agent: ConversationalAgent):
    isolated_ctx.home_state.clear()
    result = await agent.process_message("क्या घर में सब ठीक है?")
    assert result["language"] == "hindi"
    assert "शांत" in result["speech"] or "सामान्य" in result["speech"]
    assert result["incident"] is None

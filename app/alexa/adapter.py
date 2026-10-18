"""
app/alexa/adapter.py
====================
Alexa+ Integration Layer for HomeOps-AI.

Translates conversational Alexa+ requests into HomeOps operations, invokes the
HomeOps MCP layer, and formats structured responses while strictly preserving
the deterministic safety policy.

Architecture
------------
Alexa Request
     ↓
AlexaAdapter (intent classification & session context)
     ↓
HomeOpsMCPClient
     ↓
Streamable HTTP (or In-Process Server)
     ↓
HomeOps MCP Server Tools
     ↓
Deterministic Incident Engine & Safety Policy
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from app.alexa.models import AlexaIntent, AlexaRequest, AlexaResponse
from app.mcp.client import HomeOpsMCPClient, MCPClientError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent Matching Patterns (Deterministic Utterance Classification)
# ---------------------------------------------------------------------------

_INTENT_PATTERNS: list[tuple[AlexaIntent, list[re.Pattern[str]]]] = [
    (
        AlexaIntent.HOME_STATUS,
        [
            re.compile(r"what('?s| is) happening( at home)?", re.IGNORECASE),
            re.compile(r"(home|house) status", re.IGNORECASE),
            re.compile(r"check (the |my )?(home|house)", re.IGNORECASE),
            re.compile(r"how (is|are) (things|the house|everything)", re.IGNORECASE),
            re.compile(r"status report", re.IGNORECASE),
        ],
    ),
    (
        AlexaIntent.INVESTIGATE_INCIDENT,
        [
            re.compile(r"why did you say (something|an) unusual", re.IGNORECASE),
            re.compile(r"investigate( the)? incident", re.IGNORECASE),
            re.compile(r"what went wrong", re.IGNORECASE),
            re.compile(r"what happened( at home)?", re.IGNORECASE),
            re.compile(r"something happened", re.IGNORECASE),
            re.compile(r"explain( the)? (incident|unusual|alert)", re.IGNORECASE),
            re.compile(r"tell me more about the (incident|alert)", re.IGNORECASE),
            re.compile(r"check (the |my )?(back door|front door|door|window|water|basement)", re.IGNORECASE),
        ],
    ),
    (
        AlexaIntent.RISK_ASSESSMENT,
        [
            re.compile(r"how serious is it", re.IGNORECASE),
            re.compile(r"should i (be worried|worry)", re.IGNORECASE),
            re.compile(r"assess( the)? risk", re.IGNORECASE),
            re.compile(r"what('?s| is) the risk( level)?", re.IGNORECASE),
            re.compile(r"is (it|this) dangerous", re.IGNORECASE),
            re.compile(r"is (it|this|there) safe", re.IGNORECASE),
            re.compile(r"severity( level)?", re.IGNORECASE),
        ],
    ),
    (
        AlexaIntent.RECOMMENDED_RESPONSE,
        [
            re.compile(r"what should i do", re.IGNORECASE),
            re.compile(r"recommend( a)? response", re.IGNORECASE),
            re.compile(r"what (do you|would you) recommend", re.IGNORECASE),
            re.compile(r"what are my options", re.IGNORECASE),
            re.compile(r"how should i respond", re.IGNORECASE),
            re.compile(r"next steps?", re.IGNORECASE),
        ],
    ),
    (
        AlexaIntent.ACTION_REQUEST,
        [
            re.compile(r"turn off( the)?", re.IGNORECASE),
            re.compile(r"turn on( the)?", re.IGNORECASE),
            re.compile(r"arm( the)?", re.IGNORECASE),
            re.compile(r"lock( the)?", re.IGNORECASE),
            re.compile(r"unlock( the)?", re.IGNORECASE),
            re.compile(r"shut off( the)?", re.IGNORECASE),
            re.compile(r"stop( the)?", re.IGNORECASE),
            re.compile(r"execute", re.IGNORECASE),
        ],
    ),
    (
        AlexaIntent.INCIDENT_HISTORY,
        [
            re.compile(r"has this happened before", re.IGNORECASE),
            re.compile(r"incident history", re.IGNORECASE),
            re.compile(r"(check|show|get) history", re.IGNORECASE),
            re.compile(r"past incidents?", re.IGNORECASE),
            re.compile(r"previous incidents?", re.IGNORECASE),
        ],
    ),
]


class AlexaAdapter:
    """Alexa+ integration adapter for HomeOps.

    Translates Alexa voice interactions to and from the HomeOps MCP server.
    Ensures that safety policies and action boundaries are strictly respected.
    """

    def __init__(
        self,
        mcp_client: Optional[HomeOpsMCPClient] = None,
    ) -> None:
        self.mcp_client = mcp_client or HomeOpsMCPClient()
        # Session state cache: session_id -> dict
        self._session_cache: dict[str, dict[str, Any]] = {}

    # ---------------------------------------------------------------------- #
    # Public Entry Points                                                     #
    # ---------------------------------------------------------------------- #

    def handle_request(self, request: AlexaRequest) -> AlexaResponse:
        """Synchronously process an AlexaRequest."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(self.handle_request_async(request)))
                return future.result(timeout=15)
        else:
            return asyncio.run(self.handle_request_async(request))

    def handle_utterance(
        self,
        utterance: str,
        session_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> AlexaResponse:
        """Convenience method to process a raw utterance string."""
        request = AlexaRequest(
            utterance=utterance,
            session_id=session_id,
            context=context or {},
        )
        return self.handle_request(request)

    async def handle_request_async(self, request: AlexaRequest) -> AlexaResponse:
        """Asynchronously process an AlexaRequest and dispatch to appropriate handler."""
        session_id = request.session_id or "default"
        session = self._session_cache.setdefault(session_id, {})

        # Classify intent if not provided
        intent = request.intent or self._classify_intent(request.utterance)

        try:
            if intent == AlexaIntent.HOME_STATUS:
                return await self._handle_home_status(request, session)
            elif intent == AlexaIntent.INVESTIGATE_INCIDENT:
                return await self._handle_investigate_incident(request, session)
            elif intent == AlexaIntent.RISK_ASSESSMENT:
                return await self._handle_risk_assessment(request, session)
            elif intent == AlexaIntent.RECOMMENDED_RESPONSE:
                return await self._handle_recommended_response(request, session)
            elif intent == AlexaIntent.ACTION_REQUEST:
                return await self._handle_action_request(request, session)
            elif intent == AlexaIntent.INCIDENT_HISTORY:
                return await self._handle_incident_history(request, session)
            else:
                return self._handle_unknown(request)

        except MCPClientError as exc:
            logger.error("MCP communication failure while handling %s: %s", intent.value, exc)
            return AlexaResponse(
                speech=(
                    f"I encountered a communication issue with the HomeOps MCP server: {exc}. "
                    "Please ensure the HomeOps MCP server is running."
                ),
                intent=intent.value,
                data={"error": str(exc)},
            )
        except Exception as exc:
            logger.exception("Unexpected error in Alexa adapter: %s", exc)
            return AlexaResponse(
                speech=f"An unexpected error occurred while processing your request: {exc}.",
                intent=intent.value,
                data={"error": str(exc)},
            )

    # ---------------------------------------------------------------------- #
    # Intent Classifiers & Handlers                                           #
    # ---------------------------------------------------------------------- #

    def _classify_intent(self, utterance: str) -> AlexaIntent:
        """Deterministically map a user utterance to an AlexaIntent."""
        text = utterance.strip()
        for intent, patterns in _INTENT_PATTERNS:
            for pattern in patterns:
                if pattern.search(text):
                    return intent
        return AlexaIntent.UNKNOWN

    async def _handle_home_status(
        self,
        request: AlexaRequest,  # noqa: ARG002
        session: dict[str, Any],
    ) -> AlexaResponse:
        """Handle 'What's happening at home?' using get_home_state."""
        state = await self.mcp_client.get_home_state()
        session["last_home_state"] = state

        devices = state.get("devices", [])
        active_conditions = state.get("active_conditions", [])
        total_events = state.get("total_events_logged", 0)

        # Check for active alerts or anomalous device conditions
        unusual_conditions = [
            c for c in active_conditions
            if c.get("condition") in (
                "opened",
                "moisture_detected",
                "moisture_rising",
                "motion_detected",
                "detected",
            )
        ]

        if unusual_conditions:
            cond = unusual_conditions[0]
            loc = cond.get("location", "the house").replace("_", " ")
            dev = cond.get("device_type", "device").replace("_", " ")
            action = cond.get("condition", "active").replace("_", " ")
            speech = (
                f"I found one unusual event involving the {loc}. "
                f"The {dev} reported {action}. "
                "You can ask me to investigate this incident further."
            )
            incident_count = 1
            requires_confirmation = True
        elif total_events > 0:
            speech = f"All systems normal across {len(devices)} monitored devices with {total_events} recent events."
            incident_count = 0
            requires_confirmation = False
        else:
            speech = "All quiet at home. No recent sensor activity has been logged."
            incident_count = 0
            requires_confirmation = False

        return AlexaResponse(
            speech=speech,
            intent=AlexaIntent.HOME_STATUS.value,
            incident_count=incident_count,
            requires_confirmation=requires_confirmation,
            data=state,
        )

    async def _handle_investigate_incident(
        self,
        request: AlexaRequest,
        session: dict[str, Any],
    ) -> AlexaResponse:
        """Handle 'Why did you say something unusual happened?' using investigate_incident."""
        scenario = request.parameters.get("scenario")
        result = await self.mcp_client.investigate_incident(scenario=scenario)
        incidents = result.get("incidents", [])

        if not incidents:
            return AlexaResponse(
                speech="I investigated recent activity and found no active incidents. All systems are normal.",
                intent=AlexaIntent.INVESTIGATE_INCIDENT.value,
                incident_count=0,
                data=result,
            )

        primary = incidents[0]
        session["current_incident"] = primary

        # Also persist to history store via MCP record_incident tool
        try:
            await self.mcp_client.record_incident(
                incident_type=primary["incident_type"],
                severity=primary["severity"],
                confidence=primary["confidence"],
                title=primary["title"],
                summary=primary["summary"],
                evidence=primary["evidence"],
                recommended_next_step=primary["recommended_next_step"],
            )
        except Exception as exc:
            logger.warning("Could not auto-record incident to history: %s", exc)

        evidence_str = " ".join(primary.get("evidence", []))
        speech = (
            f"I detected an unusual {primary['incident_type'].replace('_', ' ').lower()} event. "
            f"{primary['summary']} "
            f"{evidence_str} "
            "Risk assessment requires confirmation before any physical response."
        )

        return AlexaResponse(
            speech=speech,
            intent=AlexaIntent.INVESTIGATE_INCIDENT.value,
            incident_count=len(incidents),
            risk_level=primary.get("severity"),
            requires_confirmation=True,
            data=result,
        )

    async def _handle_risk_assessment(
        self,
        request: AlexaRequest,
        session: dict[str, Any],
    ) -> AlexaResponse:
        """Handle 'How serious is it?' using assess_risk."""
        incident = session.get("current_incident")

        if not incident:
            # Attempt to run investigation first if no incident in session
            inv_result = await self.mcp_client.investigate_incident()
            incidents = inv_result.get("incidents", [])
            if incidents:
                incident = incidents[0]
                session["current_incident"] = incident

        if not incident:
            return AlexaResponse(
                speech="There are no active incidents to assess. All systems are currently safe.",
                intent=AlexaIntent.RISK_ASSESSMENT.value,
                risk_level="LOW",
                requires_confirmation=False,
                data={"risk_level": "LOW"},
            )

        assessment = await self.mcp_client.assess_risk(
            incident_type=incident["incident_type"],
            severity=incident["severity"],
            confidence=incident["confidence"],
            title=incident.get("title", "Incident"),
            summary=incident.get("summary", ""),
            evidence=incident.get("evidence", []),
            recommended_next_step=incident.get("recommended_next_step", ""),
        )

        risk_level = assessment.get("risk_level", "UNKNOWN")
        perm = assessment.get("action_permission", "")
        rationale = assessment.get("policy_rationale", "")

        speech = (
            f"The evaluated risk level is {risk_level}. "
            f"Action permission status is {perm}. {rationale}"
        )

        return AlexaResponse(
            speech=speech,
            intent=AlexaIntent.RISK_ASSESSMENT.value,
            incident_count=1,
            risk_level=risk_level,
            requires_confirmation=assessment.get("requires_user_confirmation", False),
            requires_explicit_approval=assessment.get("requires_explicit_approval", False),
            escalation_required=assessment.get("escalation_required", False),
            data=assessment,
        )

    async def _handle_recommended_response(
        self,
        request: AlexaRequest,
        session: dict[str, Any],
    ) -> AlexaResponse:
        """Handle 'What should I do?' using recommend_response."""
        incident = session.get("current_incident")

        if not incident:
            inv_result = await self.mcp_client.investigate_incident()
            incidents = inv_result.get("incidents", [])
            if incidents:
                incident = incidents[0]
                session["current_incident"] = incident

        if not incident:
            return AlexaResponse(
                speech="No action is needed right now. Everything is running normally.",
                intent=AlexaIntent.RECOMMENDED_RESPONSE.value,
                data={},
            )

        rec = await self.mcp_client.recommend_response(
            incident_type=incident["incident_type"],
            severity=incident["severity"],
            confidence=incident["confidence"],
            context=f"Incident {incident.get('title')}",
        )

        recommended_action = rec.get("recommended_action", "Review recent home activity.")
        speech = (
            f"I recommend: {recommended_action} "
            "Please note that HomeOps will not execute physical actions automatically."
        )

        return AlexaResponse(
            speech=speech,
            intent=AlexaIntent.RECOMMENDED_RESPONSE.value,
            incident_count=1,
            risk_level=rec.get("risk_level"),
            requires_confirmation=rec.get("requires_confirmation", True),
            requires_explicit_approval=rec.get("requires_explicit_approval", False),
            action_executed=False,
            data=rec,
        )

    async def _handle_action_request(
        self,
        request: AlexaRequest,
        session: dict[str, Any],  # noqa: ARG002
    ) -> AlexaResponse:
        """Handle 'Turn off the appliance' or 'Arm security system' via execute_safe_action.

        CRITICAL SAFETY RULE:
        In the current MVP, all physical actions are blocked by the safety policy.
        This handler must never report success and must never bypass the safety policy.
        """
        # Extract action name from parameters or parse from utterance
        action_name = request.parameters.get("action_name")
        if not action_name:
            action_name = self._extract_action_name(request.utterance)

        device_id = request.parameters.get("device_id")

        result = await self.mcp_client.execute_safe_action(
            action_name=action_name,
            device_id=device_id,
        )

        # Confirm safety boundary: executed must be False
        action_executed = result.get("executed", False)
        if action_executed:
            logger.critical("SAFETY VIOLATION: execute_safe_action claimed executed=True!")
            action_executed = False

        status = result.get("status", "blocked")
        clean_action = action_name.replace("_", " ")

        speech = (
            f"I cannot execute '{clean_action}' autonomously. "
            "HomeOps safety policy blocks autonomous physical actions in this release. "
            "Please confirm and execute this action manually via your home app."
        )

        return AlexaResponse(
            speech=speech,
            intent=AlexaIntent.ACTION_REQUEST.value,
            action_executed=False,
            action_status=status,
            requires_confirmation=True,
            requires_explicit_approval=True,
            data=result,
        )

    async def _handle_incident_history(
        self,
        request: AlexaRequest,  # noqa: ARG002
        session: dict[str, Any],  # noqa: ARG002
    ) -> AlexaResponse:
        """Handle 'Has this happened before?' by querying get_incident_history."""
        records = await self.mcp_client.get_incident_history(limit=5)

        if not records:
            speech = "I checked your home incident history. No prior incidents have been recorded."
            return AlexaResponse(
                speech=speech,
                intent=AlexaIntent.INCIDENT_HISTORY.value,
                incident_count=0,
                data={"history": []},
            )

        most_recent = records[0]
        title = most_recent.get("title", "Incident")
        sev = most_recent.get("severity", "UNKNOWN")
        speech = (
            f"I checked the incident audit history. There are {len(records)} recorded incident(s). "
            f"The most recent was a {sev} severity incident: '{title}'."
        )

        return AlexaResponse(
            speech=speech,
            intent=AlexaIntent.INCIDENT_HISTORY.value,
            incident_count=len(records),
            risk_level=sev,
            data={"history": records},
        )

    def _handle_unknown(self, request: AlexaRequest) -> AlexaResponse:
        """Handle unsupported or ambiguous utterances politely."""
        speech = (
            "I'm not sure how to handle that request. You can ask me: "
            "'What's happening at home?', "
            "'Why did you say something unusual happened?', "
            "'How serious is it?', "
            "'What should I do?', "
            "'Turn off the appliance', or "
            "'Has this happened before?'"
        )
        return AlexaResponse(
            speech=speech,
            intent=AlexaIntent.UNKNOWN.value,
            incident_count=0,
            data={"raw_utterance": request.utterance},
        )

    @staticmethod
    def _extract_action_name(utterance: str) -> str:
        """Extract a normalised action name from an utterance."""
        u = utterance.lower()
        if "appliance" in u or "turn off" in u:
            return "turn_off_configured_appliance"
        if "arm" in u or "security" in u:
            return "arm_security_system"
        if "lock" in u:
            return "lock_door"
        if "shut off" in u or "water" in u:
            return "shut_off_water_main"
        return "unspecified_physical_action"

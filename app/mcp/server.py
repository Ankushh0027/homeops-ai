"""
app/mcp/server.py
=================
HomeOps MCP server – wires MCPServer tools and starts Streamable HTTP.

This module is the assembly point:
  1. Creates the MCPServer instance.
  2. Registers the seven HomeOps tools.
  3. Provides the ``streamable_http_app()`` ASGI app for external runners.
  4. Provides a ``__main__`` entry point for direct local startup.

Usage
-----
    python -m app.mcp.server               # default: 127.0.0.1:8000
    python -m app.mcp.server --host 0.0.0.0 --port 8080

Transport: Streamable HTTP
Endpoint:  http://<host>:<port>/mcp

Design decisions
----------------
* Tool functions are imported from ``tools.py`` and wrapped in thin closures
  that inject the shared ``app_context`` dependencies.  This keeps ``tools.py``
  pure (injectable) and ``server.py`` responsible for dependency wiring.
* The MCPServer is module-level so it can be imported for ASGI deployment
  (e.g. ``uvicorn app.mcp.server:http_app``).
* No Alexa+, Bedrock, or Strands integration is present here.
* No secrets are hard-coded.  Host/port come from env vars or CLI args.
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any, Optional

from mcp.server import MCPServer

from app.mcp.context import AppContext, app_context as _default_context
from app.mcp.tools import (
    analyze_camera_footage_tool,
    assess_risk,
    execute_safe_action_tool,
    get_camera_events_tool,
    get_camera_status_tool,
    get_device_state_tool,
    get_home_state,
    get_integration_health_tool,
    get_persisted_events_tool,
    get_recent_events,
    inspect_camera_tool,
    investigate_incident,
    list_cameras_tool,
    list_devices_tool,
    record_incident,
    recommend_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(context: Optional[AppContext] = None) -> MCPServer:
    """Create and configure a HomeOps MCPServer instance.

    Parameters
    ----------
    context:
        AppContext providing home_state, engine, and history.
        Defaults to the module-level singleton (production use).
        Pass an isolated context for tests.

    Returns
    -------
    MCPServer
        Fully configured server with all seven tools registered.
    """
    ctx = context or _default_context

    server = MCPServer(
        name="HomeOps-AI",
        version="2.0.0",
        instructions=(
            "HomeOps-AI is an AI incident-response system for connected homes. "
            "It correlates home events into structured incidents, evaluates risk "
            "deterministically, and recommends safe responses. "
            "Physical device actions are NOT executed automatically. "
            "All safety decisions are deterministic and auditable."
        ),
    )

    # ------------------------------------------------------------------ #
    # Tool 1: get_home_state                                              #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="get_home_state",
        description=(
            "Return the current simulated connected-home state including devices, "
            "active conditions, and occupancy context. "
            "Optionally filter by location."
        ),
    )
    def _get_home_state(location: Optional[str] = None) -> dict[str, Any]:
        return get_home_state(location=location, ctx=ctx.home_state)

    # ------------------------------------------------------------------ #
    # Tool 2: get_recent_events                                           #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="get_recent_events",
        description=(
            "Retrieve recent home sensor events. "
            "Supports filtering by location, device_type, and event_type. "
            "Limit is clamped to [1, 200]."
        ),
    )
    def _get_recent_events(
        limit: int = 50,
        location: Optional[str] = None,
        device_type: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> dict[str, Any]:
        return get_recent_events(
            limit=limit,
            location=location,
            device_type=device_type,
            event_type=event_type,
            ctx=ctx.home_state,
        )

    # ------------------------------------------------------------------ #
    # Tool 3: investigate_incident                                        #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="investigate_incident",
        description=(
            "Run the deterministic HomeOps incident correlation engine. "
            "Optionally load a named simulator scenario "
            "('security_incident', 'water_hazard', 'leaving_home') "
            "or inject raw event dicts. "
            "Returns correlated incidents with severity, confidence, and evidence."
        ),
    )
    def _investigate_incident(
        scenario: Optional[str] = None,
        raw_events: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        return investigate_incident(
            scenario=scenario,
            raw_events=raw_events,
            ctx_state=ctx.home_state,
            ctx_engine=ctx.engine,
        )

    # ------------------------------------------------------------------ #
    # Tool 4: assess_risk                                                 #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="assess_risk",
        description=(
            "Evaluate the deterministic safety policy for a described incident. "
            "Returns risk level, action permissions, and audit trail. "
            "Severity must be one of LOW, MEDIUM, HIGH, CRITICAL. "
            "Incident type must be one of SECURITY, WATER_HAZARD, LEAVING_HOME, UNKNOWN."
        ),
    )
    def _assess_risk(
        incident_type: str,
        severity: str,
        confidence: float,
        title: str = "Incident",
        summary: str = "Risk assessment requested via MCP.",
        evidence: Optional[list[str]] = None,
        recommended_next_step: str = "Review incident details.",
    ) -> dict[str, Any]:
        return assess_risk(
            incident_type=incident_type,
            severity=severity,
            confidence=confidence,
            title=title,
            summary=summary,
            evidence=evidence,
            recommended_next_step=recommended_next_step,
        )

    # ------------------------------------------------------------------ #
    # Tool 5: recommend_response                                          #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="recommend_response",
        description=(
            "Return a safe response recommendation based on incident type and severity. "
            "This is a recommendation only – no physical action is executed. "
            "Returns risk level, confirmation requirements, and allowed safe actions."
        ),
    )
    def _recommend_response(
        incident_type: str,
        severity: str,
        confidence: float,
        context: Optional[str] = None,
    ) -> dict[str, Any]:
        return recommend_response(
            incident_type=incident_type,
            severity=severity,
            confidence=confidence,
            context=context,
        )

    # ------------------------------------------------------------------ #
    # Tool 6: execute_safe_action                                         #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="execute_safe_action",
        description=(
            "Action gateway for future agent integrations. "
            "In the current MVP this tool ALWAYS returns a 'blocked' response. "
            "No physical device action is ever executed. "
            "This boundary exists so Alexa+/Strands agents have a safe action hook "
            "when the full human-in-the-loop approval flow is implemented."
        ),
    )
    def _execute_safe_action(
        action_name: str,
        device_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return execute_safe_action_tool(
            action_name=action_name,
            device_id=device_id,
        )

    # ------------------------------------------------------------------ #
    # Tool 7: record_incident                                             #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="record_incident",
        description=(
            "Record an investigated incident to the local audit history store (SQLite). "
            "The safety policy is evaluated before recording. "
            "Returns the incident_id and confirmation of recording."
        ),
    )
    def _record_incident(
        incident_type: str,
        severity: str,
        confidence: float,
        title: str,
        summary: str,
        evidence: list[str],
        recommended_next_step: str,
    ) -> dict[str, Any]:
        return record_incident(
            incident_type=incident_type,
            severity=severity,
            confidence=confidence,
            title=title,
            summary=summary,
            evidence=evidence,
            recommended_next_step=recommended_next_step,
            ctx_history=ctx.history,
        )

    # ------------------------------------------------------------------ #
    # Tool 8: list_cameras                                                #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="list_cameras",
        description=(
            "List all configured cameras in the smart home. "
            "Returns safe metadata including camera ID, name, location, and verified status. "
            "Never exposes camera credentials or private stream URLs."
        ),
    )
    def _list_cameras() -> dict[str, Any]:
        return list_cameras_tool(camera_svc=ctx.camera_service)

    # ------------------------------------------------------------------ #
    # Tool 9: get_camera_status                                           #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="get_camera_status",
        description=(
            "Retrieve verified operational status for a specific camera ID. "
            "Status values: DEMO, CONNECTED, OFFLINE, or ERROR. "
            "Never claims connection without genuine verification."
        ),
    )
    def _get_camera_status(camera_id: str) -> dict[str, Any]:
        return get_camera_status_tool(camera_id=camera_id, camera_svc=ctx.camera_service)

    # ------------------------------------------------------------------ #
    # Tool 10: inspect_camera                                             #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="inspect_camera",
        description=(
            "Inspect a camera's location, footage availability, and recent events. "
            "Handles offline or missing cameras with explicit diagnostic errors."
        ),
    )
    def _inspect_camera(camera_id: str) -> dict[str, Any]:
        return inspect_camera_tool(camera_id=camera_id, camera_svc=ctx.camera_service)

    # ------------------------------------------------------------------ #
    # Tool 11: analyze_camera_footage                                     #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="analyze_camera_footage",
        description=(
            "Run real video object-detection inference on available camera footage. "
            "Decodes frames and detects person class using Torchvision neural network. "
            "Persists genuine detection evidence to the home state log. "
            "Never fabricates confidence or bounding box data."
        ),
    )
    def _analyze_camera_footage(
        camera_id: str,
        confidence_threshold: float = 0.40,
        max_duration_sec: int = 60,
    ) -> dict[str, Any]:
        return analyze_camera_footage_tool(
            camera_id=camera_id,
            confidence_threshold=confidence_threshold,
            max_duration_sec=max_duration_sec,
            camera_svc=ctx.camera_service,
        )

    # ------------------------------------------------------------------ #
    # Tool 12: get_camera_events                                          #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="get_camera_events",
        description=(
            "Retrieve persisted sensor and detection events for a specific camera ID. "
            "Reads genuine persisted records from the home event log."
        ),
    )
    def _get_camera_events(camera_id: str, limit: int = 50) -> dict[str, Any]:
        return get_camera_events_tool(
            camera_id=camera_id,
            limit=limit,
            camera_svc=ctx.camera_service,
        )

    # ------------------------------------------------------------------ #
    # Tool 13: list_devices                                               #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="list_devices",
        description=(
            "List smart-home devices discovered from Home Assistant, camera sources, "
            "and simulator fixtures. Distinguishes physical from simulated devices."
        ),
    )
    async def _list_devices(source: Optional[str] = None) -> dict[str, Any]:
        return await list_devices_tool(source=source, mgr=ctx.integration_manager)

    # ------------------------------------------------------------------ #
    # Tool 14: get_device_state                                           #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="get_device_state",
        description=(
            "Retrieve current telemetry state, attributes, and origin provider for a device ID."
        ),
    )
    async def _get_device_state(device_id: str) -> dict[str, Any]:
        return await get_device_state_tool(device_id=device_id, mgr=ctx.integration_manager)

    # ------------------------------------------------------------------ #
    # Tool 15: get_integration_health                                     #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="get_integration_health",
        description=(
            "Check integration health and connection status for Home Assistant, Cameras, "
            "and Simulator. Reports truthfully whether physical devices are connected."
        ),
    )
    async def _get_integration_health() -> dict[str, Any]:
        return await get_integration_health_tool(mgr=ctx.integration_manager)

    # ------------------------------------------------------------------ #
    # Tool 16: get_persisted_events                                       #
    # ------------------------------------------------------------------ #

    @server.tool(
        name="get_persisted_events",
        description=(
            "Read recent persisted home events with optional filtering by device_id or source "
            "('home_assistant', 'camera', 'simulator')."
        ),
    )
    def _get_persisted_events(
        limit: int = 50,
        device_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> dict[str, Any]:
        return get_persisted_events_tool(
            limit=limit,
            device_id=device_id,
            source=source,
            ctx=ctx.home_state,
        )

    tool_count = len(server._tool_manager.list_tools())
    logger.info(
        "HomeOps MCPServer created with %d tools.",
        tool_count,
    )
    return server


# ---------------------------------------------------------------------------
# Module-level ASGI app (for uvicorn / gunicorn deployment)
# ---------------------------------------------------------------------------

# This is the default server instance used for production and deployment.
# Tests call create_server(context=...) to get isolated instances.
_server = create_server()

# Expose the Starlette ASGI app for uvicorn:
#   uvicorn app.mcp.server:http_app
http_app = _server.streamable_http_app()


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the HomeOps MCP server with Streamable HTTP transport."""
    parser = argparse.ArgumentParser(description="HomeOps MCP Server")
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Bind host (default: 127.0.0.1, env: MCP_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Bind port (default: 8000, env: MCP_PORT)",
    )
    parser.add_argument(
        "--load-scenario",
        choices=["security_incident", "water_hazard", "leaving_home"],
        default=None,
        help="Pre-load a simulator scenario on startup.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if args.load_scenario:
        from app.mcp.context import app_context
        count = app_context.home_state.load_scenario(args.load_scenario)
        logger.info("Pre-loaded scenario '%s': %d events.", args.load_scenario, count)

    logger.info(
        "Starting HomeOps MCP Server | transport=Streamable HTTP | "
        "endpoint=http://%s:%d/mcp",
        args.host,
        args.port,
    )
    logger.info("Press Ctrl+C to stop.")

    _server.run_streamable_http_async(host=args.host, port=args.port)


if __name__ == "__main__":
    main()

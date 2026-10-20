"""
app/web/server.py
=================
Unified Web and MCP Server for HomeOps-AI.

Serves:
  - Streamable HTTP MCP server mounted at `/mcp`
  - RESTful APIs for conversational chat, investigations, device states, and safety policy
  - Static Single-Page Application (SPA) for the Alexa+-inspired HomeOps assistant UI

Transport: Real Streamable HTTP (MCP SDK 2.2.0)
"""

from __future__ import annotations

import argparse
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import httpx2
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.alexa.conversational_agent import ConversationalAgent
from app.mcp.client import HomeOpsMCPClient
from app.mcp.context import AppContext, app_context as _default_context
from app.mcp.server import create_server

logger = logging.getLogger("homeops.web")

_STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    utterance: str = Field(..., min_length=1, description="User spoken or typed utterance.")
    session_id: Optional[str] = Field(default="demo-session", description="Conversation session ID.")
    scenario_hint: Optional[str] = Field(default=None, description="Optional active scenario context.")


class ScenarioRequest(BaseModel):
    scenario: str = Field(..., description="Scenario name: 'security_incident', 'water_hazard', 'leaving_home', or 'clear'.")


class ActionApprovalRequest(BaseModel):
    action_name: str = Field(..., description="Action name to verify/request.")
    device_id: Optional[str] = Field(default=None, description="Device ID.")
    confirmed: bool = Field(default=False, description="User explicit confirmation flag.")


# ---------------------------------------------------------------------------
# Endpoint & URL Resolution Helpers
# ---------------------------------------------------------------------------

def resolve_mcp_endpoint(request: Optional[Request] = None) -> str:
    """Resolve the public MCP Streamable HTTP endpoint URL.

    Derivation priority:
      1. Explicit PUBLIC_BASE_URL environment variable (if configured)
      2. Incoming HTTP Request headers (respecting reverse-proxy X-Forwarded-* headers)
      3. Safe local fallback (http://127.0.0.1:8000/mcp)
    """
    public_base = os.getenv("PUBLIC_BASE_URL")
    if public_base and public_base.strip():
        return f"{public_base.strip().rstrip('/')}/mcp"

    if request:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        if host:
            return f"{proto}://{host}/mcp"
        return f"{str(request.base_url).rstrip('/')}/mcp"

    return "http://127.0.0.1:8000/mcp"


# ---------------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------------

def create_app(context: Optional[AppContext] = None) -> FastAPI:
    """Create and configure the unified FastAPI application and Streamable HTTP MCP server."""
    ctx = context or _default_context
    mcp_server = create_server(context=ctx)
    mcp_asgi_app = mcp_server.streamable_http_app()

    env_str = os.getenv("ENVIRONMENT", "development").lower()
    is_production = env_str == "production"

    @asynccontextmanager
    async def lifespan(app_inst: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Initializing HomeOps MCP Streamable HTTP session manager...")

        # Warm-up and verify SQLite incident history store at startup
        from app.services.incident_history import incident_history
        try:
            incident_history.count()
            logger.info("SQLite incident history store verified at startup.")
        except Exception as exc:
            logger.warning("SQLite initialization check encountered: %s", exc)

        async with mcp_asgi_app.router.lifespan_context(mcp_asgi_app):
            transport = httpx2.ASGITransport(app=mcp_asgi_app)
            mcp_client = HomeOpsMCPClient(
                base_url="http://127.0.0.1:8000/mcp",
                context=ctx,
                transport=transport,
            )
            agent = ConversationalAgent(mcp_client=mcp_client)

            app_inst.state.mcp_server = mcp_server
            app_inst.state.mcp_client = mcp_client
            app_inst.state.agent = agent
            app_inst.state.context = ctx

            # Preload default scenario
            ctx.home_state.load_scenario("security_incident")
            logger.info("Preloaded default scenario: 'security_incident'")

            yield

        logger.info("HomeOps MCP Streamable HTTP session manager shut down.")

    app_inst = FastAPI(
        title="HomeOps-AI",
        description="Conversational smart-home assistant with deterministic safety engine and Streamable HTTP MCP.",
        version="2.0.0",
        lifespan=lifespan,
        debug=not is_production,
    )

    allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
    allowed_origins = [o.strip() for o in allowed_origins_raw.split(",") if o.strip()]
    allow_creds = False if allowed_origins == ["*"] else True

    app_inst.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register real Streamable HTTP MCP routes directly on app_inst
    for r in mcp_asgi_app.routes:
        app_inst.routes.append(r)

    # -----------------------------------------------------------------------
    # Helper getters
    # -----------------------------------------------------------------------
    def _get_agent(req: Request) -> ConversationalAgent:
        agent = getattr(req.app.state, "agent", None)
        if not agent:
            raise HTTPException(status_code=503, detail="Conversational agent not initialized.")
        return agent

    def _get_client(req: Request) -> HomeOpsMCPClient:
        client = getattr(req.app.state, "mcp_client", None)
        if not client:
            raise HTTPException(status_code=503, detail="MCP client not initialized.")
        return client

    def _get_ctx(req: Request) -> AppContext:
        return getattr(req.app.state, "context", ctx)

    # -----------------------------------------------------------------------
    # API Routes
    # -----------------------------------------------------------------------

    @app_inst.post("/api/chat")
    async def chat_endpoint(payload: ChatRequest, request: Request) -> dict[str, Any]:
        """Process conversational turn using ConversationalAgent & real MCP tools."""
        agent = _get_agent(request)
        try:
            return await agent.process_message(
                utterance=payload.utterance,
                session_id=payload.session_id or "demo-session",
                scenario_hint=payload.scenario_hint,
            )
        except Exception as exc:
            logger.exception("Chat processing error: %s", exc)
            detail_msg = "An internal error occurred while processing the request." if is_production else str(exc)
            raise HTTPException(status_code=500, detail=detail_msg) from exc

    @app_inst.get("/api/home-state")
    async def get_home_state_endpoint(request: Request, location: Optional[str] = None) -> dict[str, Any]:
        client = _get_client(request)
        return await client.get_home_state(location=location)

    @app_inst.get("/api/events")
    async def get_events_endpoint(request: Request, limit: int = 50, location: Optional[str] = None) -> dict[str, Any]:
        client = _get_client(request)
        return await client.get_recent_events(limit=limit, location=location)

    @app_inst.post("/api/investigate")
    async def investigate_endpoint(request: Request, scenario: Optional[str] = None) -> dict[str, Any]:
        client = _get_client(request)
        return await client.investigate_incident(scenario=scenario)

    @app_inst.post("/api/assess-risk")
    async def assess_risk_endpoint(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        client = _get_client(request)
        return await client.assess_risk(
            incident_type=payload.get("incident_type", "SECURITY"),
            severity=payload.get("severity", "HIGH"),
            confidence=float(payload.get("confidence", 0.85)),
            title=payload.get("title", "Incident"),
            summary=payload.get("summary", ""),
            evidence=payload.get("evidence", []),
            recommended_next_step=payload.get("recommended_next_step", "Inspect entry."),
        )

    @app_inst.post("/api/recommend-response")
    async def recommend_response_endpoint(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        client = _get_client(request)
        return await client.recommend_response(
            incident_type=payload.get("incident_type", "SECURITY"),
            severity=payload.get("severity", "HIGH"),
            confidence=float(payload.get("confidence", 0.85)),
            context=payload.get("context"),
        )

    @app_inst.post("/api/execute-action")
    async def execute_action_endpoint(payload: ActionApprovalRequest, request: Request) -> dict[str, Any]:
        client = _get_client(request)
        return await client.execute_safe_action(
            action_name=payload.action_name,
            device_id=payload.device_id,
        )

    @app_inst.get("/api/history")
    async def get_history_endpoint(request: Request, limit: int = 50) -> list[dict[str, Any]]:
        client = _get_client(request)
        return await client.get_incident_history(limit=limit)

    @app_inst.post("/api/scenario")
    async def set_scenario_endpoint(payload: ScenarioRequest, request: Request) -> dict[str, Any]:
        context = _get_ctx(request)
        scen = payload.scenario.strip().lower()
        context.home_state.clear()

        if scen == "clear":
            return {
                "status": "cleared",
                "scenario": None,
                "events_loaded": 0,
                "message": "Home state cleared. All systems quiet and normal.",
            }

        valid_scenarios = ["security_incident", "water_hazard", "leaving_home"]
        if scen not in valid_scenarios:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scenario '{scen}'. Must be one of: {valid_scenarios} or 'clear'.",
            )

        count = context.home_state.load_scenario(scen)
        return {
            "status": "loaded",
            "scenario": scen,
            "events_loaded": count,
            "message": f"Loaded scenario '{scen}' with {count} events into home state.",
        }

    @app_inst.get("/api/mcp/status")
    async def get_mcp_status_endpoint(request: Request) -> dict[str, Any]:
        server_obj = getattr(request.app.state, "mcp_server", mcp_server)
        client_obj = getattr(request.app.state, "mcp_client", None)
        context_obj = getattr(request.app.state, "context", ctx)

        tool_list = [t.name for t in server_obj._tool_manager.list_tools()]
        audit_count = len(client_obj.call_audit_log) if client_obj else 0
        recent_calls = client_obj.call_audit_log[-10:] if client_obj else []

        current_scenario = getattr(context_obj.home_state, "_loaded_scenario", None)
        event_count = len(context_obj.home_state._events)

        return {
            "mcp_server": {
                "name": "HomeOps-AI",
                "version": "2.0.0",
                "endpoint": resolve_mcp_endpoint(request),
                "transport": "Streamable HTTP (MCP SDK 2.2.0)",
                "status": "online",
                "tools_registered": len(tool_list),
                "tool_names": tool_list,
            },
            "safety_policy": {
                "enforcement_mode": "STRICT_DETERMINISTIC",
                "autonomous_physical_action": "BLOCKED_BY_DEFAULT",
                "guardrail_status": "ACTIVE_PROTECTION",
                "human_in_the_loop_required": True,
            },
            "simulation": {
                "is_simulated": True,
                "current_scenario": current_scenario or "custom / live",
                "events_in_memory": event_count,
                "home_id": context_obj.home_state.HOME_ID,
            },
            "mcp_client_stats": {
                "total_tool_calls_executed": audit_count,
                "recent_tool_calls": recent_calls,
            },
        }

    @app_inst.get("/health")
    @app_inst.get("/healthz")
    async def health_check_endpoint() -> dict[str, Any]:
        """Health-check endpoint for orchestrators and monitoring (Render, curl, k8s).

        Performs a fast, safe probe without requiring a browser session or triggering
        any unsafe physical or simulated actions.
        """
        return {
            "status": "healthy",
            "service": "HomeOps-AI",
            "version": "2.0.0",
            "environment": os.getenv("ENVIRONMENT", "development"),
            "safety_policy": "STRICT_DETERMINISTIC",
        }

    # Static assets
    if _STATIC_DIR.exists():
        app_inst.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app_inst.get("/")
    async def index_page() -> FileResponse:
        index_file = _STATIC_DIR / "index.html"
        if not index_file.exists():
            return JSONResponse({"status": "HomeOps API active. Frontend assets not yet built."})
        return FileResponse(index_file)

    return app_inst


# Module-level default application instance for uvicorn
app = create_app()


def run_web_server(host: Optional[str] = None, port: Optional[int] = None) -> None:
    import uvicorn
    final_host = host or os.getenv("HOST", "0.0.0.0" if (os.getenv("PORT") or os.getenv("RENDER")) else "127.0.0.1")
    final_port = port if port is not None else int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=final_host, port=final_port, log_level="info")


if __name__ == "__main__":
    default_host = os.getenv("HOST", "0.0.0.0" if (os.getenv("PORT") or os.getenv("RENDER")) else "127.0.0.1")
    default_port = int(os.getenv("PORT", "8000"))
    parser = argparse.ArgumentParser(description="HomeOps-AI Web & MCP Server")
    parser.add_argument("--host", default=default_host, help=f"Bind host (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Bind port (default: {default_port})")
    args = parser.parse_args()
    run_web_server(host=args.host, port=args.port)

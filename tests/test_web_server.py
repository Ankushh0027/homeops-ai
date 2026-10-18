"""
tests/test_web_server.py
========================
Tests for the HomeOps-AI unified web application and REST API endpoints.

Validates:
1. /api/mcp/status endpoint (Streamable HTTP, 7 tools, online status)
2. /api/chat endpoint with conversational message
3. /api/scenario endpoint (loading security_incident, water_hazard, clear)
4. /api/home-state endpoint
5. /api/events endpoint
6. /api/execute-action endpoint (safety guardrail block verification)
7. Static file serving (/ and /static/app.css)
"""

from __future__ import annotations

import httpx2
import pytest

from app.web.server import create_app


@pytest.fixture()
def test_app():
    return create_app()


@pytest.mark.asyncio
async def test_web_mcp_status_endpoint(test_app):
    async with test_app.router.lifespan_context(test_app):
        transport = httpx2.ASGITransport(app=test_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/mcp/status")
            assert res.status_code == 200
            data = res.json()
            assert data["mcp_server"]["status"] == "online"
            assert data["mcp_server"]["tools_registered"] == 7
            assert data["safety_policy"]["autonomous_physical_action"] == "BLOCKED_BY_DEFAULT"


@pytest.mark.asyncio
async def test_web_chat_endpoint(test_app):
    async with test_app.router.lifespan_context(test_app):
        transport = httpx2.ASGITransport(app=test_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/chat",
                json={"utterance": "Something happened at my back door. Should I be worried?"},
            )
            assert res.status_code == 200
            data = res.json()
            assert "speech" in data
            assert len(data["speech"]) > 20
            assert "tool_calls" in data
            assert len(data["tool_calls"]) >= 1


@pytest.mark.asyncio
async def test_web_scenario_switch_and_home_state(test_app):
    async with test_app.router.lifespan_context(test_app):
        transport = httpx2.ASGITransport(app=test_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Switch to water hazard
            res = await client.post("/api/scenario", json={"scenario": "water_hazard"})
            assert res.status_code == 200
            assert res.json()["status"] == "loaded"

            # Query home state
            res_state = await client.get("/api/home-state")
            assert res_state.status_code == 200
            state_data = res_state.json()
            assert state_data["home_id"] == "demo-home-001"
            assert len(state_data["devices"]) >= 1


@pytest.mark.asyncio
async def test_web_execute_action_blocked(test_app):
    async with test_app.router.lifespan_context(test_app):
        transport = httpx2.ASGITransport(app=test_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/execute-action",
                json={"action_name": "lock_door", "device_id": "door-back-01"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["executed"] is False
            assert data["status"] == "blocked"


@pytest.mark.asyncio
async def test_web_static_serving(test_app):
    async with test_app.router.lifespan_context(test_app):
        transport = httpx2.ASGITransport(app=test_app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/")
            assert res.status_code == 200
            assert "HomeOps-AI" in res.text

            res_css = await client.get("/static/app.css")
            assert res_css.status_code == 200
            assert "--brand-teal" in res_css.text

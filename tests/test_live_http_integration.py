"""
tests/test_live_http_integration.py
===================================
Separate-process network HTTP integration tests.

Distinguishes from in-process ASGI mocks by testing against an actual live
server running on http://127.0.0.1:8000 over TCP sockets:
1. TCP Network connection to http://127.0.0.1:8000/mcp
2. Real Streamable HTTP MCP handshake with official mcp.client.streamable_http
3. Tool execution over live socket
4. REST API /api/chat invocation over live socket
5. Safety boundary enforcement over live socket
"""

from __future__ import annotations

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def is_live_server_running(url: str = "http://127.0.0.1:8000") -> bool:
    """Check if the external server is currently running."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{url}/api/mcp/status", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


@pytest.mark.skipif(
    not is_live_server_running(),
    reason="Live uvicorn server is not running on 127.0.0.1:8000. Start with: python -m uvicorn app.web.server:app --host 127.0.0.1 --port 8000",
)
@pytest.mark.asyncio
async def test_live_streamable_http_mcp_socket():
    """Verify live separate-process MCP communication over network socket."""
    timeout = httpx2.Timeout(10.0)
    async with httpx2.AsyncClient(timeout=timeout) as http_client:
        async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http_client) as (read_s, write_s):
            async with ClientSession(read_s, write_s) as session:
                await session.initialize()

                # Call get_home_state over live network socket
                res = await session.call_tool("get_home_state", {})
                assert res.structured_content is not None
                assert res.structured_content["home_id"] == "demo-home-001"
                assert "devices" in res.structured_content


@pytest.mark.skipif(
    not is_live_server_running(),
    reason="Live uvicorn server is not running on 127.0.0.1:8000.",
)
@pytest.mark.asyncio
async def test_live_chat_and_safety_block_socket():
    """Verify live separate-process REST chat and safety block over network socket."""
    async with httpx2.AsyncClient(base_url="http://127.0.0.1:8000", timeout=10.0) as client:
        # 1. Test chat endpoint
        chat_resp = await client.post(
            "/api/chat",
            json={"utterance": "Something happened at my back door. Should I be worried?"},
        )
        assert chat_resp.status_code == 200
        data = chat_resp.json()
        assert "back door" in data["speech"].lower()
        assert data["risk"]["risk_level"] == "HIGH"

        # 2. Test action boundary block
        action_resp = await client.post(
            "/api/execute-action",
            json={"action_name": "lock_door", "device_id": "door-back-01"},
        )
        assert action_resp.status_code == 200
        act_data = action_resp.json()
        assert act_data["executed"] is False
        assert act_data["status"] == "blocked"

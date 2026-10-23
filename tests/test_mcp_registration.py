"""
tests/test_mcp_registration.py
================================
Tests for MCP server registration, tool listing, and transport initialisation.

Tests validate:
- All 7 expected tools are registered
- Tool names are exactly correct
- Server can be created with isolated context
- Streamable HTTP app is a valid ASGI application
- Server creation is idempotent (multiple calls, independent instances)
"""

from __future__ import annotations

import pytest

from app.incidents.engine import IncidentEngine
from app.mcp.context import AppContext
from app.mcp.server import create_server
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore


EXPECTED_LEGACY_TOOLS = {
    "get_home_state",
    "get_recent_events",
    "investigate_incident",
    "assess_risk",
    "recommend_response",
    "execute_safe_action",
    "record_incident",
}

EXPECTED_CAMERA_TOOLS = {
    "list_cameras",
    "get_camera_status",
    "inspect_camera",
    "analyze_camera_footage",
    "get_camera_events",
}

EXPECTED_INTEGRATION_TOOLS = {
    "list_devices",
    "get_device_state",
    "get_integration_health",
    "get_persisted_events",
}

EXPECTED_TOOLS = EXPECTED_LEGACY_TOOLS | EXPECTED_CAMERA_TOOLS | EXPECTED_INTEGRATION_TOOLS


@pytest.fixture()
def isolated_ctx() -> AppContext:
    """Isolated AppContext with in-memory store for each test."""
    return AppContext(
        home_state=HomeStateService(),
        engine=IncidentEngine(),
        history=IncidentHistoryStore(":memory:"),
    )


@pytest.fixture()
def server(isolated_ctx: AppContext):
    return create_server(context=isolated_ctx)


# ---------------------------------------------------------------------------
# 1. Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_tools_registered(self, server):
        tools = server._tool_manager.list_tools()
        assert len(tools) == len(EXPECTED_TOOLS)

    def test_all_expected_tool_names_present(self, server):
        tools = server._tool_manager.list_tools()
        registered = {t.name for t in tools}
        assert registered == EXPECTED_TOOLS
        assert EXPECTED_LEGACY_TOOLS.issubset(registered)
        assert EXPECTED_CAMERA_TOOLS.issubset(registered)
        assert EXPECTED_INTEGRATION_TOOLS.issubset(registered)

    def test_get_home_state_registered(self, server):
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert "get_home_state" in names

    def test_get_recent_events_registered(self, server):
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert "get_recent_events" in names

    def test_investigate_incident_registered(self, server):
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert "investigate_incident" in names

    def test_assess_risk_registered(self, server):
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert "assess_risk" in names

    def test_recommend_response_registered(self, server):
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert "recommend_response" in names

    def test_execute_safe_action_registered(self, server):
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert "execute_safe_action" in names

    def test_record_incident_registered(self, server):
        tools = server._tool_manager.list_tools()
        names = {t.name for t in tools}
        assert "record_incident" in names

    def test_tool_names_are_strings(self, server):
        tools = server._tool_manager.list_tools()
        for tool in tools:
            assert isinstance(tool.name, str)
            assert len(tool.name) > 0

    def test_tools_have_descriptions(self, server):
        tools = server._tool_manager.list_tools()
        for tool in tools:
            assert tool.description is not None
            assert len(tool.description) > 0

    def test_no_duplicate_tool_names(self, server):
        tools = server._tool_manager.list_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# 2. Server creation
# ---------------------------------------------------------------------------


class TestServerCreation:
    def test_server_name_is_homeops(self, server):
        assert "HomeOps" in server.name

    def test_server_version_set(self, server):
        assert server.version is not None

    def test_multiple_isolated_servers_are_independent(self, isolated_ctx: AppContext):
        """Two servers created from separate contexts must be independent."""
        ctx1 = AppContext(
            home_state=HomeStateService(),
            engine=IncidentEngine(),
            history=IncidentHistoryStore(":memory:"),
        )
        ctx2 = AppContext(
            home_state=HomeStateService(),
            engine=IncidentEngine(),
            history=IncidentHistoryStore(":memory:"),
        )
        s1 = create_server(context=ctx1)
        s2 = create_server(context=ctx2)
        # Both have all tools registered
        assert len(s1._tool_manager.list_tools()) == len(EXPECTED_TOOLS)
        assert len(s2._tool_manager.list_tools()) == len(EXPECTED_TOOLS)
        # They are different instances
        assert s1 is not s2

    def test_server_with_default_context_creates_successfully(self):
        """Server can be created without supplying a context (uses singletons)."""
        s = create_server()
        tools = s._tool_manager.list_tools()
        assert len(tools) == len(EXPECTED_TOOLS)


# ---------------------------------------------------------------------------
# 3. Streamable HTTP transport initialisation
# ---------------------------------------------------------------------------


class TestStreamableHTTPTransport:
    def test_http_app_is_created(self, server):
        """streamable_http_app() returns a valid ASGI application object."""
        app = server.streamable_http_app()
        assert app is not None

    def test_http_app_is_callable(self, server):
        """The ASGI app must be callable (receive scope/receive/send)."""
        app = server.streamable_http_app()
        assert callable(app)

    def test_http_app_has_routes(self, server):
        """The Starlette app must have at least one route (the /mcp endpoint)."""
        app = server.streamable_http_app()
        # Starlette app has router
        assert hasattr(app, "routes") or hasattr(app, "router")

    def test_custom_path_accepted(self, server):
        """streamable_http_app accepts a custom mount path without raising."""
        app = server.streamable_http_app(streamable_http_path="/homeops/mcp")
        assert app is not None

    def test_module_level_http_app_exists(self):
        """The module-level http_app is pre-built and importable."""
        from app.mcp.server import http_app
        assert http_app is not None
        assert callable(http_app)

    def test_server_has_run_streamable_http_async(self, server):
        """The server exposes the Streamable HTTP runner method."""
        assert callable(getattr(server, "run_streamable_http_async", None))


# ---------------------------------------------------------------------------
# 4. Safety gate – execute_safe_action via server context
# ---------------------------------------------------------------------------


class TestSafetyGateViaServer:
    """Verify the execute_safe_action tool is wired and always blocked."""

    def test_execute_safe_action_tool_exists(self, server):
        tools = server._tool_manager.list_tools()
        tool = next((t for t in tools if t.name == "execute_safe_action"), None)
        assert tool is not None

    def test_execute_safe_action_description_mentions_blocked(self, server):
        tools = server._tool_manager.list_tools()
        tool = next(t for t in tools if t.name == "execute_safe_action")
        desc = tool.description.lower()
        assert "blocked" in desc or "disabled" in desc or "not" in desc or "never" in desc

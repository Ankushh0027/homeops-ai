"""
app/mcp/context.py
==================
Shared application context for the HomeOps MCP server.

Holds the module-level singletons that MCP tool handlers use.  Keeping
them in one place makes dependency injection easy for tests and avoids
circular imports.

Design decisions
----------------
* Context is a plain dataclass – no magic.
* Tool handlers import ``app_context`` and access ``.home_state``,
  ``.engine``, and ``.history`` directly.
* Tests can swap out any of these with test doubles without patching.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.incidents.engine import IncidentEngine
from app.services.home_state import HomeStateService, home_state as _default_home_state
from app.services.incident_history import IncidentHistoryStore, incident_history as _default_history
from app.cameras.service import CameraService, camera_service as _default_camera_service
from app.integrations.manager import IntegrationManager, integration_manager as _default_integration_manager


@dataclass
class AppContext:
    """Container for the application singletons used by MCP tools."""

    home_state: HomeStateService = field(default_factory=lambda: _default_home_state)
    engine: IncidentEngine = field(default_factory=IncidentEngine)
    history: IncidentHistoryStore = field(default_factory=lambda: _default_history)
    camera_service: CameraService = field(default_factory=lambda: _default_camera_service)
    integration_manager: IntegrationManager = field(default_factory=lambda: _default_integration_manager)


# Module-level singleton used by tool handlers.
# Tests construct their own AppContext with isolated state.
app_context = AppContext()


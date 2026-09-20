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


@dataclass
class AppContext:
    """Container for the application singletons used by MCP tools."""

    home_state: HomeStateService = field(default_factory=lambda: _default_home_state)
    engine: IncidentEngine = field(default_factory=IncidentEngine)
    history: IncidentHistoryStore = field(default_factory=lambda: _default_history)


# Module-level singleton used by tool handlers.
# Tests construct their own AppContext with isolated state.
app_context = AppContext()

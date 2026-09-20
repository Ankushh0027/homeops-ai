"""
app/services/home_state.py
==========================
Simulated home state service.

Manages the current in-memory representation of the connected home:
  - active devices and their last-known state
  - the rolling event log (capped ring buffer)
  - occupancy context

This service is the single source of truth for MCP tools that need to query
or update home state.  It wraps the simulator JSON scenarios so that the MCP
layer never directly reads files — it asks the service.

Design decisions
----------------
* Pure in-memory state for the MVP.  No DynamoDB or cloud state store yet.
* The service is a module-level singleton (``home_state``) rather than a
  class instance per request; it represents the home, not a session.
* Thread-safety is not needed yet (asyncio single-thread event loop).
* Scenarios can be loaded explicitly (useful for tests and for the CLI).
* The event log is capped at ``MAX_EVENTS`` to avoid unbounded memory growth.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.models.events import HomeEvent

logger = logging.getLogger(__name__)

MAX_EVENTS: int = 500
_SCENARIOS_DIR = Path(__file__).parent.parent.parent / "simulator" / "scenarios"
_SAMPLE_EVENTS = Path(__file__).parent.parent.parent / "simulator" / "events" / "sample_events.json"

SCENARIO_FILES: dict[str, str] = {
    "security_incident": "security_incident.json",
    "water_hazard": "water_hazard.json",
    "leaving_home": "leaving_home.json",
}


class Device:
    """Lightweight in-memory representation of a connected device."""

    def __init__(
        self,
        device_id: str,
        device_type: str,
        location: str,
        last_event_type: str,
        last_seen: datetime,
        last_value: Any = None,
    ) -> None:
        self.device_id = device_id
        self.device_type = device_type
        self.location = location
        self.last_event_type = last_event_type
        self.last_seen = last_seen
        self.last_value = last_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "location": self.location,
            "last_event_type": self.last_event_type,
            "last_seen": self.last_seen.isoformat(),
            "last_value": self.last_value,
        }


class HomeStateService:
    """In-memory home state service.

    Holds the rolling event log and device state.  Provides query methods
    used by MCP tool handlers.
    """

    HOME_ID: str = "demo-home-001"

    def __init__(self) -> None:
        self._events: deque[HomeEvent] = deque(maxlen=MAX_EVENTS)
        self._devices: dict[str, Device] = {}
        self._loaded_scenario: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Scenario / event loading                                            #
    # ------------------------------------------------------------------ #

    def load_scenario(self, name: str) -> int:
        """Load a named simulator scenario into the event log.

        Returns the number of events loaded.
        """
        filename = SCENARIO_FILES.get(name)
        if filename is None:
            raise ValueError(
                f"Unknown scenario {name!r}. "
                f"Available: {sorted(SCENARIO_FILES.keys())}"
            )
        path = _SCENARIOS_DIR / filename
        events = self._load_json_events(path)
        self._events.extend(events)
        self._loaded_scenario = name
        self._rebuild_device_state()
        logger.info("Loaded %d events from scenario '%s'.", len(events), name)
        return len(events)

    def load_sample_events(self) -> int:
        """Load the sample_events.json file into the event log."""
        events = self._load_json_events(_SAMPLE_EVENTS)
        self._events.extend(events)
        self._rebuild_device_state()
        logger.info("Loaded %d sample events.", len(events))
        return len(events)

    def add_event(self, event: HomeEvent) -> None:
        """Add a single validated event to the log and update device state."""
        self._events.append(event)
        self._update_device(event)

    def clear(self) -> None:
        """Reset event log and device state (useful in tests)."""
        self._events.clear()
        self._devices.clear()
        self._loaded_scenario = None

    # ------------------------------------------------------------------ #
    # Query API (used by MCP tools)                                       #
    # ------------------------------------------------------------------ #

    def get_recent_events(
        self,
        limit: int = 50,
        location: Optional[str] = None,
        device_type: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> list[HomeEvent]:
        """Return recent events newest-first, optionally filtered."""
        limit = max(1, min(limit, MAX_EVENTS))
        events = list(self._events)
        # Apply filters
        if location:
            events = [e for e in events if e.location == location]
        if device_type:
            events = [e for e in events if e.device_type == device_type]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        # Newest first
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def get_all_events(self) -> list[HomeEvent]:
        """Return all events in chronological order (for the incident engine)."""
        return sorted(self._events, key=lambda e: e.timestamp)

    def get_home_state(self, location: Optional[str] = None) -> dict[str, Any]:
        """Return a structured snapshot of the home state."""
        devices = list(self._devices.values())
        if location:
            devices = [d for d in devices if d.location == location]

        # Derive active conditions from device state
        active_conditions: list[dict[str, str]] = []
        for d in devices:
            active_conditions.append(
                {
                    "device_id": d.device_id,
                    "device_type": d.device_type,
                    "condition": d.last_event_type,
                    "location": d.location,
                }
            )

        # Simple occupancy summary
        occupancy = self._get_occupancy_summary()

        return {
            "home_id": self.HOME_ID,
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "loaded_scenario": self._loaded_scenario,
            "location_filter": location,
            "total_events_logged": len(self._events),
            "devices": [d.to_dict() for d in devices],
            "active_conditions": active_conditions,
            "occupancy": occupancy,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _load_json_events(self, path: Path) -> list[HomeEvent]:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("events", data) if isinstance(data, dict) else data
        return [HomeEvent.model_validate(e) for e in raw]

    def _rebuild_device_state(self) -> None:
        """Replay all events in order to rebuild device state."""
        self._devices.clear()
        for event in sorted(self._events, key=lambda e: e.timestamp):
            self._update_device(event)

    def _update_device(self, event: HomeEvent) -> None:
        """Update (or create) a device entry from an event."""
        self._devices[event.device_id] = Device(
            device_id=event.device_id,
            device_type=event.device_type,
            location=event.location,
            last_event_type=event.event_type,
            last_seen=event.timestamp,
            last_value=event.value,
        )

    def _get_occupancy_summary(self) -> dict[str, Any]:
        """Derive a simple occupancy summary from occupancy sensor events."""
        occupancy_devices = {
            d for d in self._devices.values()
            if d.device_type == "occupancy_sensor"
        }
        person_detected = any(
            d.last_event_type == "person_detected" for d in occupancy_devices
        )
        user_departing = any(
            d.last_event_type == "user_departing" for d in occupancy_devices
        )
        return {
            "person_detected": person_detected,
            "user_departing": user_departing,
            "occupancy_sensors_count": len(occupancy_devices),
        }


# Module-level singleton – all MCP tools share this state.
home_state = HomeStateService()

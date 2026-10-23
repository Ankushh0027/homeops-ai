"""
app/integrations/simulator/provider.py
======================================
Deterministic simulated device provider for HomeOps-AI.

Guarantees:
1. Complete isolation: All simulated devices have is_simulated=True and provider_id="simulator".
2. Deterministic scenarios: Provides repeatable sensor telemetry for testing
   security incidents, water hazards, departures, smoke alerts, and sensor failures.
3. Explicit enablement: Disabled in production by default; rejected if SIMULATOR_ENABLED is false.
4. Preserves origin: Events carry metadata={"source": "simulator", "is_simulated": True}.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import settings
from app.integrations.base import (
    DeviceMetadata,
    IntegrationHealth,
    IntegrationProvider,
    IntegrationStatus,
)
from app.models.events import HomeEvent

logger = logging.getLogger("homeops.integrations.simulator")


class SimulatedDeviceProvider(IntegrationProvider):
    """Deterministic simulated smart-home device provider."""

    provider_id = "simulator"
    name = "HomeOps Device Simulator"

    def __init__(self, enabled: Optional[bool] = None) -> None:
        self.enabled = enabled if enabled is not None else settings.SIMULATOR_ENABLED
        self._active_scenario: Optional[str] = "security_incident" if self.enabled else None
        self._last_sync_time: Optional[datetime] = None
        self._pending_events: list[HomeEvent] = []

        # Default simulated fixture inventory
        self._devices: dict[str, DeviceMetadata] = {
            "sim-door-front": DeviceMetadata(
                device_id="sim-door-front",
                name="Front Door Contact Sensor (Simulated)",
                device_type="door_sensor",
                location="front_door",
                provider_id=self.provider_id,
                is_simulated=True,
                state="closed",
                status="ACTIVE",
                attributes={"protocol": "simulated", "battery": 95},
            ),
            "sim-door-back": DeviceMetadata(
                device_id="sim-door-back",
                name="Back Door Contact Sensor (Simulated)",
                device_type="door_sensor",
                location="back_door",
                provider_id=self.provider_id,
                is_simulated=True,
                state="opened",
                status="ACTIVE",
                attributes={"protocol": "simulated", "battery": 88},
            ),
            "sim-motion-hallway": DeviceMetadata(
                device_id="sim-motion-hallway",
                name="Hallway Motion Detector (Simulated)",
                device_type="motion_sensor",
                location="hallway",
                provider_id=self.provider_id,
                is_simulated=True,
                state="cleared",
                status="ACTIVE",
                attributes={"protocol": "simulated", "battery": 92},
            ),
            "sim-water-laundry": DeviceMetadata(
                device_id="sim-water-laundry",
                name="Laundry Water Leak Detector (Simulated)",
                device_type="water_sensor",
                location="laundry_room",
                provider_id=self.provider_id,
                is_simulated=True,
                state="moisture_cleared",
                status="ACTIVE",
                attributes={"protocol": "simulated", "battery": 100},
            ),
            "sim-smoke-kitchen": DeviceMetadata(
                device_id="sim-smoke-kitchen",
                name="Kitchen Smoke Detector (Simulated)",
                device_type="smoke_sensor",
                location="kitchen",
                provider_id=self.provider_id,
                is_simulated=True,
                state="smoke_cleared",
                status="ACTIVE",
                attributes={"protocol": "simulated", "battery": 90},
            ),
            "sim-sensor-attic": DeviceMetadata(
                device_id="sim-sensor-attic",
                name="Attic Temperature & Contact (Simulated Offline)",
                device_type="door_sensor",
                location="attic",
                provider_id=self.provider_id,
                is_simulated=True,
                state="unavailable",
                status="OFFLINE",
                attributes={"protocol": "simulated", "offline_reason": "RF signal out of range"},
            ),
            "sim-lock-front": DeviceMetadata(
                device_id="sim-lock-front",
                name="Front Door Smart Lock (Simulated)",
                device_type="lock_sensor",
                location="front_door",
                provider_id=self.provider_id,
                is_simulated=True,
                state="locked",
                status="ACTIVE",
                attributes={"protocol": "simulated", "battery": 91, "locked": True},
            ),
            "sim-tank-water": DeviceMetadata(
                device_id="sim-tank-water",
                name="Overhead Water Tank Level (Simulated)",
                device_type="water_tank_sensor",
                location="utility_roof",
                provider_id=self.provider_id,
                is_simulated=True,
                state="82%",
                status="ACTIVE",
                attributes={"protocol": "simulated", "level_pct": 82, "capacity_liters": 1000},
            ),
            "sim-cam-gate": DeviceMetadata(
                device_id="sim-cam-gate",
                name="Main Gate Demo Camera",
                device_type="camera",
                location="main_gate",
                provider_id=self.provider_id,
                is_simulated=True,
                state="active",
                status="DEMO",
                attributes={"protocol": "synthetic_mp4", "clip": "main_gate_demo.mp4"},
            ),
        }

    async def get_health(self) -> IntegrationHealth:
        status = IntegrationStatus.CONNECTED if self.enabled else IntegrationStatus.DISABLED
        return IntegrationHealth(
            provider_id=self.provider_id,
            name=self.name,
            status=status,
            is_configured=True,
            is_connected=self.enabled,
            device_count=len(self._devices) if self.enabled else 0,
            error_message=None if self.enabled else "Simulator disabled in this environment.",
            last_sync=self._last_sync_time.isoformat() if self._last_sync_time else None,
            metadata={
                "enabled": self.enabled,
                "active_scenario": self._active_scenario,
                "is_simulated": True,
            },
        )

    async def discover_devices(self) -> list[DeviceMetadata]:
        if not self.enabled:
            return []
        return list(self._devices.values())

    async def sync_events(self) -> list[HomeEvent]:
        if not self.enabled:
            return []
        events = list(self._pending_events)
        self._pending_events.clear()
        self._last_sync_time = datetime.now(timezone.utc)
        return events

    def trigger_scenario(self, scenario_name: str) -> list[HomeEvent]:
        """Trigger a deterministic scenario fixture.

        Raises PermissionError if simulator is disabled.
        """
        if not self.enabled:
            raise PermissionError("Simulator is disabled in this environment.")

        name = scenario_name.strip().lower()
        now_utc = datetime.now(timezone.utc)
        new_events: list[HomeEvent] = []

        if name == "security_incident":
            # Back door opened + hallway motion + person detection
            self._devices["sim-door-back"].state = "opened"
            self._devices["sim-motion-hallway"].state = "detected"
            new_events = [
                HomeEvent(
                    device_id="sim-door-back",
                    device_type="door_sensor",
                    event_type="opened",
                    location="back_door",
                    timestamp=now_utc,
                    metadata={"source": "simulator", "is_simulated": True, "scenario": name},
                ),
                HomeEvent(
                    device_id="sim-motion-hallway",
                    device_type="motion_sensor",
                    event_type="detected",
                    location="hallway",
                    timestamp=now_utc,
                    metadata={"source": "simulator", "is_simulated": True, "scenario": name},
                ),
            ]
        elif name == "water_hazard":
            self._devices["sim-water-laundry"].state = "moisture_detected"
            new_events = [
                HomeEvent(
                    device_id="sim-water-laundry",
                    device_type="water_sensor",
                    event_type="moisture_detected",
                    location="laundry_room",
                    timestamp=now_utc,
                    metadata={"source": "simulator", "is_simulated": True, "scenario": name},
                ),
            ]
        elif name == "smoke_alert":
            self._devices["sim-smoke-kitchen"].state = "smoke_detected"
            new_events = [
                HomeEvent(
                    device_id="sim-smoke-kitchen",
                    device_type="smoke_sensor",
                    event_type="smoke_detected",
                    location="kitchen",
                    timestamp=now_utc,
                    metadata={"source": "simulator", "is_simulated": True, "scenario": name},
                ),
            ]
        elif name == "leaving_home":
            self._devices["sim-door-front"].state = "opened"
            new_events = [
                HomeEvent(
                    device_id="sim-door-front",
                    device_type="door_sensor",
                    event_type="opened",
                    location="front_door",
                    timestamp=now_utc,
                    metadata={"source": "simulator", "is_simulated": True, "scenario": name},
                ),
            ]
        elif name in {"clear", "quiet_home"}:
            for dev in self._devices.values():
                if dev.device_type == "door_sensor":
                    dev.state = "closed"
                elif dev.device_type == "motion_sensor":
                    dev.state = "cleared"
                elif dev.device_type == "water_sensor":
                    dev.state = "moisture_cleared"
                elif dev.device_type == "smoke_sensor":
                    dev.state = "smoke_cleared"
                elif dev.device_type == "lock_sensor":
                    dev.state = "locked"
                elif dev.device_type == "water_tank_sensor":
                    dev.state = "82%"
            new_events = []
        else:
            raise ValueError(f"Unknown scenario '{scenario_name}'. Available: security_incident, water_hazard, smoke_alert, leaving_home, clear.")

        self._active_scenario = name
        self._pending_events.extend(new_events)
        return new_events

    async def close(self) -> None:
        self._pending_events.clear()

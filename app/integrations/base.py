"""
app/integrations/base.py
========================
Provider-independent integration contracts and base models for HomeOps-AI.

Supports:
- Home Assistant
- IP and Network Cameras (RTSP/ONVIF)
- Simulated Device Providers
- Contact, Motion, Water, Smoke, and Environment Sensors

Key Principles:
1. Provider independence: The incident engine and state layers never couple
   to Home Assistant or camera-specific wire formats.
2. Honest status reporting: Never report CONNECTED without a successful connection.
3. Simulation transparency: All simulated devices and events explicitly carry
   is_simulated=True and preserve their origin source.
4. Credential security: Access tokens and credentials are never stored in
   event models or device metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.events import HomeEvent


class IntegrationStatus(str, Enum):
    """Accurate health and connectivity status for an integration provider."""
    UNCONFIGURED = "UNCONFIGURED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    AUTH_ERROR = "AUTH_ERROR"
    UNREACHABLE = "UNREACHABLE"
    ERROR = "ERROR"
    DISABLED = "DISABLED"


class DeviceMetadata(BaseModel):
    """Normalized metadata for a discovered or configured smart-home device."""

    device_id: str = Field(..., min_length=1, description="Unique normalized device ID.")
    name: str = Field(..., description="Human-readable device label.")
    device_type: str = Field(..., description="Normalized device type (e.g. 'door_sensor', 'camera').")
    location: str = Field(..., description="Location label (e.g. 'front_door', 'main_gate').")
    provider_id: str = Field(..., description="Provider source: 'home_assistant', 'camera', or 'simulator'.")
    is_simulated: bool = Field(default=False, description="True if device is synthetic/simulated; False if physical.")
    state: Optional[str] = Field(default=None, description="Current device state (e.g. 'closed', 'motion_detected').")
    last_seen: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the last known telemetry or health check.",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive extra attributes (e.g. battery, firmware, original entity_id).",
    )
    status: str = Field(default="ACTIVE", description="Device operational status: 'ACTIVE', 'DEMO', 'OFFLINE'.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "device_type": self.device_type,
            "location": self.location,
            "provider_id": self.provider_id,
            "is_simulated": self.is_simulated,
            "state": self.state,
            "last_seen": self.last_seen.isoformat(),
            "attributes": self.attributes,
            "status": self.status,
        }


class IntegrationHealth(BaseModel):
    """Health check summary for a specific integration provider."""

    provider_id: str
    name: str
    status: IntegrationStatus
    is_configured: bool
    is_connected: bool
    device_count: int = 0
    error_message: Optional[str] = None
    last_sync: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "status": self.status.value,
            "is_configured": self.is_configured,
            "is_connected": self.is_connected,
            "device_count": self.device_count,
            "error_message": self.error_message,
            "last_sync": self.last_sync,
            "metadata": self.metadata,
        }


class IntegrationProvider(ABC):
    """Abstract base class for all hardware and simulator integration providers."""

    provider_id: str
    name: str

    @abstractmethod
    async def get_health(self) -> IntegrationHealth:
        """Return truthful health and connection status."""
        raise NotImplementedError

    @abstractmethod
    async def discover_devices(self) -> list[DeviceMetadata]:
        """Discover and return all normalized devices known to this provider."""
        raise NotImplementedError

    @abstractmethod
    async def sync_events(self) -> list[HomeEvent]:
        """Perform a bounded synchronization turn and return newly observed events."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Cleanly close any network sockets, sessions, or background resources."""
        raise NotImplementedError

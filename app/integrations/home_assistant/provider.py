"""
app/integrations/home_assistant/provider.py
===========================================
Home Assistant Integration Provider for HomeOps-AI.

Interacts with Home Assistant Core REST and WebSocket APIs:
- Authentication verification: GET /api/
- Entity state discovery: GET /api/states
- Entity and event normalization to HomeOps domain types
- State-transition duplicate suppression
- Strict credential redaction (tokens are never logged or exposed)
- Truthful health reporting (UNCONFIGURED, CONNECTING, CONNECTED, AUTH_ERROR, UNREACHABLE)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx2

from app.config import settings
from app.integrations.base import (
    DeviceMetadata,
    IntegrationHealth,
    IntegrationProvider,
    IntegrationStatus,
)
from app.models.events import HomeEvent

logger = logging.getLogger("homeops.integrations.home_assistant")


def _mask_token(token: Optional[str]) -> str:
    """Safely describe token presence without revealing secrets."""
    if not token or not token.strip():
        return "not_set"
    trimmed = token.strip()
    if len(trimmed) <= 8:
        return "***"
    return f"{trimmed[:4]}...{trimmed[-4:]} (len={len(trimmed)})"


def _sanitize_url(url: Optional[str]) -> str:
    """Validate and sanitize the Home Assistant URL."""
    if not url or not url.strip():
        return ""
    u = url.strip().rstrip("/")
    # Prevent SSRF to cloud metadata endpoints
    parsed = urlparse(u)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"169.254.169.254", "metadata.google.internal", "instance-data"}:
        raise ValueError(f"Prohibited metadata destination: {hostname}")
    return u


class HomeAssistantProvider(IntegrationProvider):
    """Home Assistant integration provider for physical hubs and devices."""

    provider_id = "home_assistant"
    name = "Home Assistant"

    def __init__(
        self,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx2.AsyncClient] = None,
    ) -> None:
        raw_url = base_url if base_url is not None else settings.HOME_ASSISTANT_URL
        self._base_url = _sanitize_url(raw_url) if raw_url else ""
        self._access_token = (
            access_token if access_token is not None else (settings.HOME_ASSISTANT_TOKEN or "")
        ).strip()
        self._timeout = timeout_seconds or settings.HOME_ASSISTANT_TIMEOUT_SECONDS
        self._custom_client = http_client
        self._client: Optional[httpx2.AsyncClient] = http_client
        self._last_health: IntegrationStatus = IntegrationStatus.UNCONFIGURED
        self._last_error: Optional[str] = None
        self._last_sync_time: Optional[datetime] = None
        # Track last known states for duplicate event suppression
        self._last_entity_states: dict[str, str] = {}
        self._last_entity_timestamps: dict[str, str] = {}

    @property
    def is_configured(self) -> bool:
        """Return True if both URL and access token are provided."""
        return bool(self._base_url and self._access_token)

    def _get_client(self) -> httpx2.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            self._client = httpx2.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx2.Timeout(self._timeout),
            )
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    async def get_health(self) -> IntegrationHealth:
        """Truthful health check probe against Home Assistant /api/."""
        if not self.is_configured:
            return IntegrationHealth(
                provider_id=self.provider_id,
                name=self.name,
                status=IntegrationStatus.UNCONFIGURED,
                is_configured=False,
                is_connected=False,
                device_count=0,
                error_message="Home Assistant URL or token not configured.",
                last_sync=self._last_sync_time.isoformat() if self._last_sync_time else None,
                metadata={"url": self._base_url, "token_status": _mask_token(self._access_token)},
            )

        client = self._get_client()
        try:
            resp = await client.get("/api/", headers=self._auth_headers())
            if resp.status_code == 200:
                self._last_health = IntegrationStatus.CONNECTED
                self._last_error = None
                return IntegrationHealth(
                    provider_id=self.provider_id,
                    name=self.name,
                    status=IntegrationStatus.CONNECTED,
                    is_configured=True,
                    is_connected=True,
                    device_count=len(self._last_entity_states),
                    error_message=None,
                    last_sync=self._last_sync_time.isoformat() if self._last_sync_time else None,
                    metadata={"url": self._base_url, "message": resp.json().get("message", "API running")},
                )
            elif resp.status_code in {401, 403}:
                self._last_health = IntegrationStatus.AUTH_ERROR
                self._last_error = f"Authentication rejected by Home Assistant (HTTP {resp.status_code})."
                return IntegrationHealth(
                    provider_id=self.provider_id,
                    name=self.name,
                    status=IntegrationStatus.AUTH_ERROR,
                    is_configured=True,
                    is_connected=False,
                    device_count=0,
                    error_message=self._last_error,
                    last_sync=self._last_sync_time.isoformat() if self._last_sync_time else None,
                    metadata={"url": self._base_url, "status_code": resp.status_code},
                )
            else:
                self._last_health = IntegrationStatus.ERROR
                self._last_error = f"Unexpected response from Home Assistant: HTTP {resp.status_code}"
                return IntegrationHealth(
                    provider_id=self.provider_id,
                    name=self.name,
                    status=IntegrationStatus.ERROR,
                    is_configured=True,
                    is_connected=False,
                    device_count=0,
                    error_message=self._last_error,
                    last_sync=self._last_sync_time.isoformat() if self._last_sync_time else None,
                    metadata={"url": self._base_url, "status_code": resp.status_code},
                )
        except (httpx2.ConnectError, httpx2.TimeoutException, httpx2.NetworkError) as exc:
            self._last_health = IntegrationStatus.UNREACHABLE
            self._last_error = f"Cannot reach Home Assistant: {exc.__class__.__name__}"
            return IntegrationHealth(
                provider_id=self.provider_id,
                name=self.name,
                status=IntegrationStatus.UNREACHABLE,
                is_configured=True,
                is_connected=False,
                device_count=0,
                error_message=self._last_error,
                last_sync=self._last_sync_time.isoformat() if self._last_sync_time else None,
                metadata={"url": self._base_url, "exception": str(exc)},
            )
        except Exception as exc:
            self._last_health = IntegrationStatus.ERROR
            self._last_error = str(exc)
            return IntegrationHealth(
                provider_id=self.provider_id,
                name=self.name,
                status=IntegrationStatus.ERROR,
                is_configured=True,
                is_connected=False,
                device_count=0,
                error_message=str(exc),
                last_sync=self._last_sync_time.isoformat() if self._last_sync_time else None,
                metadata={"url": self._base_url},
            )

    async def discover_devices(self) -> list[DeviceMetadata]:
        """Fetch all states from Home Assistant and normalize them into DeviceMetadata."""
        if not self.is_configured:
            return []

        client = self._get_client()
        try:
            resp = await client.get("/api/states", headers=self._auth_headers())
            if resp.status_code != 200:
                logger.warning("Failed to retrieve HA states: HTTP %d", resp.status_code)
                return []

            raw_states = resp.json()
            devices: list[DeviceMetadata] = []
            for item in raw_states:
                dev = self._normalize_entity_to_device(item)
                if dev:
                    devices.append(dev)
            return devices
        except Exception as exc:
            logger.error("Error discovering devices from Home Assistant: %s", exc)
            return []

    async def sync_events(self) -> list[HomeEvent]:
        """Poll current states, compare with previous states, and emit events for changes."""
        if not self.is_configured:
            return []

        client = self._get_client()
        try:
            resp = await client.get("/api/states", headers=self._auth_headers())
            if resp.status_code != 200:
                return []

            raw_states = resp.json()
            events: list[HomeEvent] = []
            now_utc = datetime.now(timezone.utc)

            for item in raw_states:
                entity_id = item.get("entity_id", "")
                state_val = str(item.get("state", "")).lower()
                last_changed = item.get("last_changed") or item.get("last_updated") or ""

                # Duplicate suppression check
                prev_state = self._last_entity_states.get(entity_id)
                prev_timestamp = self._last_entity_timestamps.get(entity_id)

                if prev_state is not None and prev_state == state_val and prev_timestamp == last_changed:
                    # No state transition or timestamp change -> suppress duplicate
                    continue

                # State changed or newly observed
                self._last_entity_states[entity_id] = state_val
                self._last_entity_timestamps[entity_id] = last_changed

                # Do not emit events for the initial cold discovery unless it represents an active safety event
                if prev_state is None and state_val not in {"on", "detected", "moisture_detected", "smoke_detected"}:
                    continue

                ev = self._normalize_entity_to_event(item, now_utc)
                if ev:
                    events.append(ev)

            self._last_sync_time = now_utc
            return events
        except Exception as exc:
            logger.error("Error during Home Assistant event sync: %s", exc)
            return []

    def _normalize_entity_to_device(self, state_dict: dict[str, Any]) -> Optional[DeviceMetadata]:
        """Convert a Home Assistant state object into normalized DeviceMetadata."""
        entity_id: str = state_dict.get("entity_id", "")
        if not entity_id or "." not in entity_id:
            return None

        domain, object_id = entity_id.split(".", 1)
        attrs = state_dict.get("attributes", {})
        device_class = str(attrs.get("device_class", "")).lower()
        friendly_name = attrs.get("friendly_name") or object_id.replace("_", " ").title()

        device_type = self._map_domain_to_device_type(domain, device_class)
        if not device_type:
            return None

        location = self._derive_location(object_id, friendly_name)
        state_str = str(state_dict.get("state", "unknown"))

        return DeviceMetadata(
            device_id=f"ha-{entity_id}",
            name=friendly_name,
            device_type=device_type,
            location=location,
            provider_id=self.provider_id,
            is_simulated=False,
            state=state_str,
            status="OFFLINE" if state_str in {"unavailable", "unknown"} else "ACTIVE",
            attributes={
                "ha_entity_id": entity_id,
                "device_class": device_class,
                "battery_level": attrs.get("battery_level"),
            },
        )

    def _normalize_entity_to_event(
        self, state_dict: dict[str, Any], event_timestamp: datetime
    ) -> Optional[HomeEvent]:
        """Convert a Home Assistant state transition into a normalized HomeEvent."""
        entity_id: str = state_dict.get("entity_id", "")
        domain, object_id = entity_id.split(".", 1)
        attrs = state_dict.get("attributes", {})
        device_class = str(attrs.get("device_class", "")).lower()
        friendly_name = attrs.get("friendly_name") or object_id.replace("_", " ").title()

        device_type = self._map_domain_to_device_type(domain, device_class)
        if not device_type:
            return None

        raw_state = str(state_dict.get("state", "")).lower()
        event_type = self._map_state_to_event_type(device_type, raw_state)
        if not event_type:
            return None

        location = self._derive_location(object_id, friendly_name)

        return HomeEvent(
            device_id=f"ha-{entity_id}",
            device_type=device_type,
            event_type=event_type,
            location=location,
            timestamp=event_timestamp,
            value=raw_state,
            metadata={
                "source": self.provider_id,
                "is_simulated": False,
                "ha_entity_id": entity_id,
                "friendly_name": friendly_name,
            },
        )

    @staticmethod
    def _map_domain_to_device_type(domain: str, device_class: str) -> Optional[str]:
        if domain == "binary_sensor":
            if device_class in {"door", "garage_door", "opening"}:
                return "door_sensor"
            if device_class == "window":
                return "window_sensor"
            if device_class in {"motion", "occupancy"}:
                return "motion_sensor"
            if device_class in {"moisture", "water"}:
                return "water_sensor"
            if device_class in {"smoke", "gas"}:
                return "smoke_sensor"
            if device_class == "lock":
                return "lock_sensor"
            return "motion_sensor" if "motion" in device_class else "door_sensor"
        elif domain == "lock":
            return "lock_sensor"
        elif domain == "camera":
            return "camera"
        return None

    @staticmethod
    def _map_state_to_event_type(device_type: str, raw_state: str) -> Optional[str]:
        s = raw_state.strip().lower()
        if s in {"unavailable", "unknown"}:
            return "unavailable"

        if device_type in {"door_sensor", "window_sensor"}:
            return "opened" if s in {"on", "open", "opened", "true"} else "closed"
        elif device_type == "motion_sensor":
            return "detected" if s in {"on", "motion", "detected", "true"} else "cleared"
        elif device_type == "water_sensor":
            return "moisture_detected" if s in {"on", "wet", "detected", "true"} else "moisture_cleared"
        elif device_type == "smoke_sensor":
            return "smoke_detected" if s in {"on", "detected", "smoke", "true"} else "smoke_cleared"
        elif device_type == "lock_sensor":
            return "unlocked" if s in {"unlocked", "open"} else "locked"
        elif device_type == "camera":
            return "active" if s not in {"unavailable", "off", "idle"} else "inactive"
        return "active" if s == "on" else "inactive"

    @staticmethod
    def _derive_location(object_id: str, friendly_name: str) -> str:
        text = f"{object_id} {friendly_name}".lower()
        if "front" in text and ("door" in text or "gate" in text):
            return "front_door"
        if "back" in text and ("door" in text or "patio" in text):
            return "back_door"
        if "garage" in text:
            return "garage"
        if "kitchen" in text:
            return "kitchen"
        if "laundry" in text or "utility" in text:
            return "laundry_room"
        if "hallway" in text or "hall" in text:
            return "hallway"
        if "main gate" in text or "main_gate" in text:
            return "main_gate"
        return re.sub(r"[^a-z0-9_]+", "_", object_id).strip("_")

    async def close(self) -> None:
        """Close http client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

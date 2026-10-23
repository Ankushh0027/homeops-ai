"""
app/integrations/manager.py
===========================
Unified Integration Manager for HomeOps-AI.

Coordinates:
- Home Assistant provider (physical hub)
- Camera provider (physical RTSP and synthetic demo cameras)
- Simulated provider (isolated deterministic test fixtures)

Guarantees:
- Deduplication across synchronization intervals
- Transparent provenance: devices and events clearly labeled with their provider and simulation status
- Clean synchronization into HomeStateService
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.integrations.base import (
    DeviceMetadata,
    IntegrationHealth,
    IntegrationProvider,
    IntegrationStatus,
)
from app.integrations.cameras.provider import CameraIntegrationProvider
from app.integrations.home_assistant.provider import HomeAssistantProvider
from app.integrations.simulator.provider import SimulatedDeviceProvider
from app.models.events import HomeEvent
from app.services.home_state import HomeStateService, home_state as _default_home_state

logger = logging.getLogger("homeops.integrations.manager")


class IntegrationManager:
    """Coordinates smart-home integration providers and event ingestion."""

    def __init__(
        self,
        home_state_service: Optional[HomeStateService] = None,
        providers: Optional[dict[str, IntegrationProvider]] = None,
    ) -> None:
        self.home_state = home_state_service or _default_home_state
        self._providers: dict[str, IntegrationProvider] = (
            providers if providers is not None else self._build_default_providers()
        )
        self._seen_event_signatures: set[str] = set()

    def _build_default_providers(self) -> dict[str, IntegrationProvider]:
        return {
            "home_assistant": HomeAssistantProvider(),
            "camera": CameraIntegrationProvider(),
            "simulator": SimulatedDeviceProvider(),
        }

    def register_provider(self, provider: IntegrationProvider) -> None:
        """Register or replace an integration provider."""
        self._providers[provider.provider_id] = provider

    def get_provider(self, provider_id: str) -> Optional[IntegrationProvider]:
        return self._providers.get(provider_id)

    async def get_all_health(self) -> dict[str, Any]:
        """Collect health status across all registered providers."""
        statuses: dict[str, Any] = {}
        has_physical_connected = False

        for pid, prov in self._providers.items():
            health: IntegrationHealth = await prov.get_health()
            statuses[pid] = health.to_dict()
            if pid == "home_assistant" and health.is_connected:
                has_physical_connected = True
            elif pid == "camera" and health.metadata.get("has_physical_connected", False):
                has_physical_connected = True

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "has_physical_connected": has_physical_connected,
            "providers": statuses,
        }

    async def list_devices(self, source: Optional[str] = None) -> list[DeviceMetadata]:
        """List devices discovered across all providers, optionally filtered by source."""
        clean_source = source.strip().lower() if source else None
        results: list[DeviceMetadata] = []

        for pid, prov in self._providers.items():
            if clean_source and clean_source != pid:
                continue
            try:
                devs = await prov.discover_devices()
                results.extend(devs)
            except Exception as exc:
                logger.error("Error discovering devices from provider '%s': %s", pid, exc)

        return results

    async def get_device_state(self, device_id: str) -> Optional[DeviceMetadata]:
        """Find a specific device by its normalized device_id."""
        clean_id = (device_id or "").strip()
        all_devices = await self.list_devices()
        for dev in all_devices:
            if dev.device_id == clean_id:
                return dev
        return None

    async def sync_all(self) -> list[HomeEvent]:
        """Poll all providers, deduplicate events, and append new events to HomeState."""
        new_events: list[HomeEvent] = []

        for pid, prov in self._providers.items():
            try:
                events = await prov.sync_events()
                for ev in events:
                    # Deduplication key: device_id + event_type + timestamp to nearest second
                    sig = f"{ev.device_id}:{ev.event_type}:{int(ev.timestamp.timestamp())}"
                    if sig in self._seen_event_signatures:
                        continue
                    self._seen_event_signatures.add(sig)

                    # Ingest into core HomeStateService
                    self.home_state.add_event(ev)
                    new_events.append(ev)
            except Exception as exc:
                logger.error("Error syncing events from provider '%s': %s", pid, exc)

        return new_events

    async def close(self) -> None:
        """Clean up all provider connections."""
        for prov in self._providers.values():
            try:
                await prov.close()
            except Exception as exc:
                logger.warning("Error closing provider %s: %s", prov.provider_id, exc)


# Module-level default singleton
integration_manager = IntegrationManager()

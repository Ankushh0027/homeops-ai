"""
app/models/events.py
====================
Typed Pydantic models representing home sensor events.

Design decisions
----------------
* Pydantic v2 is used for runtime validation and type-safe field access.
* ``event_id`` defaults to a UUID so callers can omit it when building test
  fixtures, but it is always present on a valid model instance.
* ``timestamp`` defaults to UTC-now so event streams can be created without
  supplying times while still being ordered correctly.
* ``metadata`` is an open dict, allowing device-specific payloads (e.g.
  firmware version, battery level) without widening the core schema.
* No secrets or credentials are stored in an event.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Allowed device / event type constants
# ---------------------------------------------------------------------------

# Extend these sets as new device categories are added.
KNOWN_DEVICE_TYPES: frozenset[str] = frozenset(
    {
        "door_sensor",
        "motion_sensor",
        "water_sensor",
        "appliance",
        "occupancy_sensor",
        "light_sensor",
        "lock_sensor",
        "security_system",
        "window_sensor",
        "smoke_sensor",
        "co_sensor",
        "thermostat",
        "camera",
    }
)

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Door / window
        "opened",
        "closed",
        "locked",
        "unlocked",
        # Motion / occupancy
        "detected",
        "cleared",
        "person_detected",
        "no_person_detected",
        # Water / environment
        "moisture_detected",
        "moisture_cleared",
        "moisture_rising",
        "flood_detected",
        # Smoke / CO
        "smoke_detected",
        "smoke_cleared",
        "co_detected",
        "co_cleared",
        # Appliance
        "running",
        "stopped",
        "fault",
        # Light
        "on",
        "off",
        # Security system
        "armed",
        "disarmed",
        "triggered",
        # Generic
        "active",
        "inactive",
        "unavailable",
        "tamper",
        "user_departing",
    }
)


class HomeEvent(BaseModel):
    """A single sensor or device event emitted by the connected home.

    All fields are validated at construction time.  Raise
    ``pydantic.ValidationError`` for any constraint violation.
    """

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this event instance.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time at which the event was emitted.",
    )
    device_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the originating device.",
    )
    device_type: str = Field(
        ...,
        description="Category of the device (e.g. 'door_sensor', 'motion_sensor').",
    )
    event_type: str = Field(
        ...,
        description="What the device reported (e.g. 'opened', 'detected').",
    )
    value: Optional[Any] = Field(
        default=None,
        description="Sensor reading associated with the event (type varies by device).",
    )
    location: str = Field(
        ...,
        min_length=1,
        description="Human-readable location label (e.g. 'back_door', 'hallway').",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra payload for device-specific context.",
    )

    # ------------------------------------------------------------------ #
    # Validators                                                           #
    # ------------------------------------------------------------------ #

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str) -> str:
        if v not in KNOWN_DEVICE_TYPES:
            raise ValueError(
                f"Unknown device_type {v!r}. "
                f"Known types: {sorted(KNOWN_DEVICE_TYPES)}"
            )
        return v

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in KNOWN_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type {v!r}. "
                f"Known types: {sorted(KNOWN_EVENT_TYPES)}"
            )
        return v

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        """Ensure the timestamp is always timezone-aware (UTC)."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def age_seconds(self, reference: Optional[datetime] = None) -> float:
        """Return how many seconds old this event is relative to *reference*.

        If *reference* is omitted, the current UTC time is used.
        """
        ref = reference or datetime.now(timezone.utc)
        return (ref - self.timestamp).total_seconds()

    def __repr__(self) -> str:
        return (
            f"HomeEvent(device_id={self.device_id!r}, "
            f"device_type={self.device_type!r}, "
            f"event_type={self.event_type!r}, "
            f"location={self.location!r})"
        )

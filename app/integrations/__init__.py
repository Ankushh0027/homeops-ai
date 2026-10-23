"""
app/integrations/__init__.py
============================
Provider-independent integration package for HomeOps-AI.
"""

from app.integrations.base import (
    DeviceMetadata,
    IntegrationHealth,
    IntegrationProvider,
    IntegrationStatus,
)
from app.integrations.manager import IntegrationManager, integration_manager

__all__ = [
    "DeviceMetadata",
    "IntegrationHealth",
    "IntegrationProvider",
    "IntegrationStatus",
    "IntegrationManager",
    "integration_manager",
]

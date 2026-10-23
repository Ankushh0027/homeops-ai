"""
app/config.py
=============
Application configuration loaded exclusively from environment variables.
No secrets are ever hard-coded here.  All sensitive values must be supplied
via a .env file (not committed) or via the deployment environment.
"""

import os
from typing import Optional


class Settings:
    """Centralised, read-only configuration object.

    Attributes are populated from environment variables with safe defaults
    suitable for local development.  Production deployments must override
    values via the environment – never by editing this file.
    """

    # ------------------------------------------------------------------ #
    # General & Networking                                                 #
    # ------------------------------------------------------------------ #
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    HOST: str = os.getenv(
        "HOST",
        "0.0.0.0" if (os.getenv("PORT") or os.getenv("RENDER")) else "127.0.0.1",
    )
    PORT: int = int(os.getenv("PORT", "8000"))
    PUBLIC_BASE_URL: Optional[str] = os.getenv("PUBLIC_BASE_URL")
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")
    HOMEOPS_DB_PATH: Optional[str] = os.getenv("HOMEOPS_DB_PATH")

    # ------------------------------------------------------------------ #
    # Incident engine                                                      #
    # ------------------------------------------------------------------ #

    # Maximum seconds between events that are still treated as correlated.
    INCIDENT_CORRELATION_WINDOW_SECONDS: int = int(
        os.getenv("INCIDENT_CORRELATION_WINDOW_SECONDS", "300")
    )

    # Incidents whose confidence falls below this threshold are suppressed.
    INCIDENT_MIN_CONFIDENCE_THRESHOLD: float = float(
        os.getenv("INCIDENT_MIN_CONFIDENCE_THRESHOLD", "0.3")
    )

    # ------------------------------------------------------------------ #
    # Safety policy                                                        #
    # ------------------------------------------------------------------ #

    # Whether low-risk informational responses are permitted without
    # any user confirmation.
    SAFETY_ALLOW_INFORMATIONAL_ACTIONS: bool = (
        os.getenv("SAFETY_ALLOW_INFORMATIONAL_ACTIONS", "true").lower() == "true"
    )

    # ------------------------------------------------------------------ #
    # Future integrations & Hardware Providers                            #
    # ------------------------------------------------------------------ #
    HOME_ASSISTANT_URL: Optional[str] = os.getenv("HOME_ASSISTANT_URL")
    HOME_ASSISTANT_TOKEN: Optional[str] = os.getenv("HOME_ASSISTANT_TOKEN")
    HOME_ASSISTANT_TIMEOUT_SECONDS: float = float(
        os.getenv("HOME_ASSISTANT_TIMEOUT_SECONDS", "5.0")
    )

    # Simulator controls
    SIMULATOR_ENABLED: bool = (
        os.getenv(
            "SIMULATOR_ENABLED",
            "false" if os.getenv("ENVIRONMENT", "development").lower() == "production" else "true",
        ).lower()
        == "true"
    )
    SIMULATOR_ALLOW_SCENARIOS: bool = (
        os.getenv(
            "SIMULATOR_ALLOW_SCENARIOS",
            "false" if os.getenv("ENVIRONMENT", "development").lower() == "production" else "true",
        ).lower()
        == "true"
    )

    def __repr__(self) -> str:  # pragma: no cover
        ha_configured = bool(self.HOME_ASSISTANT_URL and self.HOME_ASSISTANT_TOKEN)
        return (
            f"Settings(env={self.ENVIRONMENT!r}, "
            f"log_level={self.LOG_LEVEL!r}, "
            f"ha_configured={ha_configured}, "
            f"simulator_enabled={self.SIMULATOR_ENABLED}, "
            f"correlation_window={self.INCIDENT_CORRELATION_WINDOW_SECONDS}s)"
        )


# Module-level singleton – import this object wherever config is needed.
settings = Settings()

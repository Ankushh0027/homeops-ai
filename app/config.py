"""
app/config.py
=============
Application configuration loaded exclusively from environment variables.
No secrets are ever hard-coded here.  All sensitive values must be supplied
via a .env file (not committed) or via the deployment environment.
"""

import os


class Settings:
    """Centralised, read-only configuration object.

    Attributes are populated from environment variables with safe defaults
    suitable for local development.  Production deployments must override
    values via the environment – never by editing this file.
    """

    # ------------------------------------------------------------------ #
    # General                                                              #
    # ------------------------------------------------------------------ #
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

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
    # Future integrations (NOT implemented in MVP)                        #
    # ------------------------------------------------------------------ #
    # MCP_ENDPOINT – set in environment only, never here.
    # BEDROCK_REGION – set in environment only, never here.
    # ALEXA_SKILL_ID – set in environment only, never here.

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Settings(env={self.ENVIRONMENT!r}, "
            f"log_level={self.LOG_LEVEL!r}, "
            f"correlation_window={self.INCIDENT_CORRELATION_WINDOW_SECONDS}s)"
        )


# Module-level singleton – import this object wherever config is needed.
settings = Settings()

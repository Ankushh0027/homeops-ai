"""
app/alexa
=========
Alexa+ integration layer for HomeOps-AI.

Exports:
  - AlexaAdapter: Translates Alexa requests into MCP operations.
  - AlexaRequest: Validated inbound interaction request.
  - AlexaResponse: Safety-preserving conversational response.
  - AlexaIntent: Enumeration of supported voice intents.
  - AlexaSimulator: Deterministic interactive CLI simulation and demo runner.
"""

from app.alexa.adapter import AlexaAdapter
from app.alexa.models import AlexaIntent, AlexaRequest, AlexaResponse

__all__ = [
    "AlexaAdapter",
    "AlexaIntent",
    "AlexaRequest",
    "AlexaResponse",
]

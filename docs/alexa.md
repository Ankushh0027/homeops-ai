# HomeOps-AI: Alexa+ Integration Layer

This document describes the **Alexa+ integration architecture** for HomeOps-AI, including how the integration connects to the Model Context Protocol (MCP) server, the deterministic safety boundaries enforced, what components are real versus simulated, and how to run the interactive demo and test suite.

---

## Architecture Overview

The Alexa+ integration connects conversational voice interactions to HomeOps's deterministic incident engine and 4-tier safety policy via the standard Model Context Protocol (MCP) over Streamable HTTP:

```
User (Voice / CLI)
     │
     ▼
Alexa+ Experience / Simulator (app/alexa/simulator.py)
     │
     ▼
Alexa Adapter (app/alexa/adapter.py)
  - Intent classification (models.py)
  - Natural speech synthesis
  - Session context tracking
     │
     ▼
HomeOps MCP Client (app/mcp/client.py)
     │
     │ Streamable HTTP (http://127.0.0.1:8000/mcp)
     ▼
HomeOps MCP Server (app/mcp/server.py)
  - get_home_state
  - get_recent_events
  - investigate_incident
  - assess_risk
  - recommend_response
  - execute_safe_action (Safety Boundary)
  - record_incident
     │
     ▼
Deterministic Application Core
  - HomeStateService (app/services/home_state.py)
  - IncidentEngine (app/incidents/engine.py)
  - SafetyPolicy (app/safety/policy.py)
  - IncidentHistoryStore (SQLite: app/services/incident_history.py)
```

---

## Real vs. Simulated Components

To maintain technical credibility and compliance with Amazon developer terms, HomeOps strictly delineates between what is live production software and what is simulated:

| Component | Status | Implementation Details |
|---|---|---|
| **HomeOps MCP Server** | **Real** | MCP SDK 2.2.0 server hosting 7 tools |
| **Transport Layer** | **Real** | Streamable HTTP (`/mcp` endpoint) |
| **Deterministic Incident Engine** | **Real** | Rule-based correlation (`app/incidents/`) |
| **Safety Policy** | **Real** | Deterministic 4-tier risk policy (`app/safety/policy.py`) |
| **Audit History** | **Real** | Persistent SQLite database (`app/services/incident_history.py`) |
| **Alexa Adapter & Models** | **Real** | Strongly typed Pydantic models & adapter (`app/alexa/`) |
| **MCP Client** | **Real** | Streamable HTTP client & in-process caller (`app/mcp/client.py`) |
| **Voice Audio & Cloud Sandbox** | **Simulated** | CLI voice prompt/response simulator (`app/alexa/simulator.py`) |

### Why Alexa+ Voice/Cloud is Simulated

Production **Alexa+ Add-ons** require an Amazon developer account with private preview access and provisioned Echo devices connected to Amazon's generative AI cloud. Because external hardware and private preview credentials are not publicly available in local development and hackathon evaluation environments, HomeOps provides the **`AlexaSimulator`** CLI.

The simulator routes through the **actual** `AlexaAdapter`, the **actual** `HomeOpsMCPClient`, the **actual** `MCPServer`, and the **actual** deterministic safety policy. No hard-coded or fake incident responses are used.

---

## Supported Conversational Intents

The adapter translates natural spoken utterances into strongly-typed `AlexaRequest` objects and dispatches to the corresponding HomeOps operations:

| Intent | Example Utterance | Underlying Operation | Safety Behavior |
|---|---|---|---|
| `HOME_STATUS` | *"What's happening at home?"* | `get_home_state` via MCP | Surfaces open doors, motion, and active alerts. |
| `INVESTIGATE_INCIDENT` | *"Why did you say something unusual happened?"* | `investigate_incident` via MCP | Correlates sensor events; explains evidence; auto-records to history. |
| `RISK_ASSESSMENT` | *"How serious is it?"* | `assess_risk` via MCP | Deterministically evaluates risk (LOW, MEDIUM, HIGH, CRITICAL). |
| `RECOMMENDED_RESPONSE` | *"What should I do?"* | `recommend_response` via MCP | Recommends safe steps; explicitly notes no physical actions are autonomous. |
| `ACTION_REQUEST` | *"Turn off the configured appliance."* | `execute_safe_action` via MCP | **Always blocked.** Never executes physical action autonomously. |
| `INCIDENT_HISTORY` | *"Has this happened before?"* | `get_incident_history` via History Store | Queries SQLite audit trail of previously recorded incidents. |
| `UNKNOWN` | *"Sing me a song."* | Fallback handler | Outlines available HomeOps voice capabilities. |

---

## Safety Boundary Enforcement

The Alexa+ integration preserves HomeOps's 4-tier deterministic safety model:

| Risk Level | Action Permission | Autonomous Physical Action? |
|---|---|---|
| **LOW** | Informational only | Permitted (informational response only) |
| **MEDIUM** | Requires user confirmation | **Blocked** until confirmed via approved interface |
| **HIGH** | Requires explicit approval | **Blocked** until explicit approval; only safe suggestions |
| **CRITICAL** | No autonomous action | **Strictly prohibited**; human escalation only |

### Critical Action Guard
1. When a user asks Alexa to execute a physical action (e.g. *"Turn off the appliance"*, *"Arm the security system"*, *"Lock the door"*), the adapter routes to `execute_safe_action`.
2. In the current release, `execute_safe_action` **always returns a structured blocked response** (`executed: false`, `status: "blocked"`).
3. The adapter **never** sets `action_executed = true`, never reports success for an action that did not occur, and explains why the safety policy prevented the action.

---

## How to Run

### 1. Run the Deterministic 11-Step Hackathon Demo

Execute the complete end-to-end hackathon demonstration:

```bash
python -m app.alexa.simulator --demo
```

This runs the 11-step scenario:
1. Ingests simulated back-door opened event.
2. Ingests motion detected in hallway/kitchen.
3. Confirms no recognised resident is present.
4. Deterministic engine correlates these into a HIGH-severity `SECURITY` incident.
5. User asks: *"What's happening at home?"* -> Alexa+ reports back-door alert.
6. User asks: *"Why did you say something unusual happened?"* -> Alexa+ investigates and explains evidence.
7. User asks: *"How serious is it?"* -> Alexa+ evaluates risk as HIGH (explicit approval required).
8. User asks: *"What should I do?"* -> Alexa+ recommends checking cameras and contacting resident.
9. User asks: *"Turn off the configured appliance."* -> Routed through safety gateway.
10. Safety policy prevents autonomous physical action (`executed: false`, `status: "blocked"`).
11. Incident is verified in persistent SQLite history (*"Has this happened before?"*).

---

### 2. Run the Interactive Simulator REPL

Start the interactive conversational prompt:

```bash
python -m app.alexa.simulator --interactive
```

Switch scenarios dynamically:

```bash
# Security incident (default)
python -m app.alexa.simulator --scenario security_incident --interactive

# Water hazard
python -m app.alexa.simulator --scenario water_hazard --interactive

# Leaving home
python -m app.alexa.simulator --scenario leaving_home --interactive
```

---

### 3. Run Over Streamable HTTP

Start the standalone MCP server in one terminal:

```bash
python -m app.mcp.server --load-scenario security_incident
```

Run the Alexa simulator connected via Streamable HTTP in another terminal:

```bash
python -m app.alexa.simulator --mcp-url http://127.0.0.1:8000/mcp --demo
```

---

### 4. Run the Test Suite

Run the full Phase 3 test suite:

```bash
pytest -v tests/test_alexa_adapter.py tests/test_alexa_simulator.py
```

Run all tests across all phases:

```bash
pytest -v tests/
```

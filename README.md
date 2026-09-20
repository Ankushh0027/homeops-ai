# HomeOps-AI

> **AI incident-response for connected homes.**
> Correlate fragmented device events into meaningful incidents, assess risk deterministically, and recommend safe responses — without autonomous physical action.

---

## What HomeOps Is

HomeOps-AI is a backend incident-correlation and safety-policy engine for
connected homes. It ingests streams of raw sensor events (door sensors, motion
detectors, water sensors, appliances, occupancy sensors, etc.), correlates
related events into structured incidents, assigns severity and confidence, and
evaluates a deterministic safety policy to decide what — if anything — the
system may do in response.

HomeOps is **not** a chatbot, a generic smart-home assistant, or a device
control system. Its core purpose is reliable, auditable, deterministic
reasoning about home safety.

---

## Why It Exists

Connected-home platforms generate dozens of isolated alerts per day. A door
opened. A motion sensor fired. An appliance is running. Individually, these are
noise. Together, in the right context, they can signal an intrusion, a water
leak, or a hazardous departure. HomeOps exists to perform that correlation and
surface actionable, risk-assessed incidents rather than raw alert floods.

---

## Current MVP Scope

Three incident scenarios are supported in the MVP:

### 1. Security Incident
Correlates:
- A door or window opened
- Motion detected shortly afterwards
- No verified occupancy (resident presence)

### 2. Home Water Hazard
Correlates:
- A water/moisture sensor triggered
- A concurrent appliance running (likely source)
- Moisture levels rising (escalation signal)

### 3. Leaving Home
On user departure, audits:
- Doors / windows left open
- Appliances still running
- Lights left on
- Security system not armed

---

## Phase Status

| Phase | Status | Description |
|---|---|---|
| **Phase 1** | ✅ Complete | Deterministic engine, safety policy, simulator, 116 tests |
| **Phase 2** | ✅ Complete | MCP server (Streamable HTTP), 7 tools, 103 MCP tests |
| **Phase 3** | Planned | Alexa+, Strands agents, Amazon Bedrock |

---

## Architecture

### Phase 1 Core

```
Simulator JSON --> HomeEvent (Pydantic) --> IncidentEngine --> Incident[]
                                                                   |
                                                                   v
                                                          evaluate_policy()
                                                                   |
                                                                   v
                                                           SafetyDecision
```

### Phase 2: MCP Layer

```
MCP Client
  |
  | Streamable HTTP  (http://host:8000/mcp)
  v
HomeOps MCP Server  (app/mcp/server.py)
  |
  +--> HomeStateService     (app/services/home_state.py)
  |
  +--> IncidentEngine       (app/incidents/engine.py)
  |
  +--> SafetyPolicy         (app/safety/policy.py)
  |
  +--> IncidentHistoryStore (app/services/incident_history.py  SQLite)
```


Key modules:

| Module | Purpose |
|---|---|
| `app/models/events.py` | Typed, validated `HomeEvent` model |
| `app/incidents/rules.py` | Deterministic correlation rules (one per scenario) |
| `app/incidents/engine.py` | `IncidentEngine` — orchestrates rules, filters by confidence |
| `app/incidents/schemas.py` | `Incident`, `Severity`, `IncidentType` |
| `app/safety/policy.py` | `evaluate_policy()`, `execute_safe_action()` guard |
| `app/safety/schemas.py` | `SafetyDecision`, `RiskLevel`, `ActionPermission` |
| `app/config.py` | Environment-variable configuration |
| `app/main.py` | CLI simulation runner |
| `simulator/scenarios/` | JSON event sequences for each scenario |
| `app/mcp/server.py` | MCPServer — wires tools, starts Streamable HTTP |
| `app/mcp/tools.py` | 7 thin MCP tool handler adapters |
| `app/mcp/context.py` | AppContext — shared dependency injection |
| `app/services/home_state.py` | In-memory home state + event log |
| `app/services/incident_history.py` | SQLite incident audit history |

See [`docs/architecture.md`](docs/architecture.md) for a full component diagram.
See [`docs/mcp.md`](docs/mcp.md) for the MCP tool reference.

---

## Safety Model

All safety decisions are **deterministic and auditable**.

| Risk Level | Permitted Response |
|---|---|
| `LOW` | Informational response – no confirmation needed |
| `MEDIUM` | Blocked until user confirms |
| `HIGH` | Blocked until explicit approval; only predefined safe actions may be presented |
| `CRITICAL` | No autonomous action of any kind; escalation/information only |

**`execute_safe_action()` always raises `AutonomousActionForbiddenError` in the
MVP.** No code path can trigger a physical device action automatically. This
guard rail must not be removed without a complete human-in-the-loop approval
workflow in place.

---

## Local Setup

**Requirements:** Python 3.11+

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd HomeOps-AI

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the environment template (no secrets required for local dev)
cp .env.example .env
```

---

## Running the Simulator

Run all three scenarios end-to-end through the full pipeline:

```bash
python -m app.main
```

Run a specific scenario:

```bash
python -m app.main --scenario security_incident
python -m app.main --scenario water_hazard
python -m app.main --scenario leaving_home
```

---

## Running the MCP Server (Phase 2)

```bash
# Default: binds to 127.0.0.1:8000
python -m app.mcp.server

# Pre-load a simulator scenario
python -m app.mcp.server --load-scenario security_incident

# Custom host and port
python -m app.mcp.server --host 0.0.0.0 --port 8080

# Via uvicorn (ASGI)
uvicorn app.mcp.server:http_app --host 0.0.0.0 --port 8000
```

MCP endpoint: `http://127.0.0.1:8000/mcp`
Transport: **Streamable HTTP** (MCP SDK 2.2.0)

See [`docs/mcp.md`](docs/mcp.md) for full tool documentation.

---

## Running Tests

```bash
# All tests (Phase 1 + Phase 2)
pytest -v tests/

# Phase 1 only
pytest -v tests/test_incident_engine.py tests/test_safety_policy.py

# Phase 2 MCP tests only
pytest -v tests/test_mcp_tools.py tests/test_mcp_registration.py
```

With coverage:

```bash
pytest -v --cov=app --cov-report=term-missing tests/
```

---

## Current Limitations

- **No real device integration.** Events come from simulator JSON files only.
- **Incident history uses SQLite.** No DynamoDB or cloud persistence yet.
- **No notification delivery.** Incidents are reported via CLI or MCP response only.
- **No LLM or AI inference.** All reasoning is deterministic rule-based logic.
- **Simulator-only home state.** The MCP server serves simulated, not real, device data.
- **Single-correlation pass.** The engine processes a batch of events once; it
  does not maintain state across time windows between invocations.

---

## Planned Integrations (Phase 3+)

| Integration | Purpose | Status |
|---|---|---|
| **MCP** (Model Context Protocol) | Expose safe home-control tools to AI agents | ✅ Complete – Phase 2 |
| **Alexa+** | Voice-driven incident reporting and confirmation | Not implemented – Phase 3 |
| **Amazon Bedrock** | LLM-powered incident summarisation and Q&A | Not implemented – Phase 3 |
| **Strands Agents** | Multi-step AI orchestration for complex incidents | Not implemented – Phase 3 |
| **Real device APIs** | Ring, SmartThings, Home Assistant | Not implemented – Phase 3 |

> **Alexa+ integration is NOT implemented.** No Alexa+ calls exist in the codebase.
> **Strands is NOT implemented.** No Strands agent code exists.
> **Bedrock is NOT implemented.** No LLM calls are made anywhere in the system.

---

## Project Structure

```
HomeOps-AI/
├── app/
│   ├── __init__.py
│   ├── main.py                     # CLI simulation runner
│   ├── config.py                   # Environment-variable configuration
│   ├── mcp/                        # Phase 2: MCP server
│   │   ├── __init__.py
│   │   ├── server.py               # MCPServer + Streamable HTTP + __main__
│   │   ├── tools.py                # 7 tool handler functions
│   │   └── context.py              # AppContext (dependency injection)
│   ├── agents/                     # Phase 3 stub: Strands/Bedrock
│   │   └── __init__.py
│   ├── incidents/
│   │   ├── engine.py               # IncidentEngine
│   │   ├── rules.py                # Correlation rules
│   │   └── schemas.py              # Incident, Severity, IncidentType
│   ├── safety/
│   │   ├── policy.py               # evaluate_policy, execute_safe_action
│   │   └── schemas.py              # SafetyDecision, RiskLevel
│   ├── services/
│   │   ├── home_state.py           # In-memory home state service
│   │   └── incident_history.py     # SQLite incident history store
│   └── models/
│       └── events.py               # HomeEvent Pydantic model
├── simulator/
│   ├── events/
│   │   └── sample_events.json
│   └── scenarios/
│       ├── security_incident.json
│       ├── water_hazard.json
│       └── leaving_home.json
├── tests/
│   ├── test_incident_engine.py     # 56 Phase 1 tests
│   ├── test_safety_policy.py       # 60 Phase 1 tests
│   ├── test_mcp_tools.py           # 81 Phase 2 MCP tool tests
│   └── test_mcp_registration.py    # 22 Phase 2 registration tests
├── docs/
│   ├── architecture.md
│   └── mcp.md                      # MCP tool reference
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── LICENSE
```

---

## License

MIT — see [`LICENSE`](LICENSE).

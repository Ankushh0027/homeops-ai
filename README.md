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

| Phase | Status | Description |
|---|---|---|
| **Phase 1** | ✅ Complete | Deterministic engine, safety policy, simulator, 116 tests |
| **Phase 2** | ✅ Complete | MCP server (Streamable HTTP), 7 tools, 103 MCP tests |
| **Phase 3** | ✅ Complete | Alexa+ integration layer, simulator, MCP client, 45 tests |
| **Phase 3.5** | ✅ Complete | Alexa+-inspired Conversational Assistant Web UI, 12 experiences, 273 tests |
| **Phase 4** | Planned | Amazon Bedrock, Strands AI agents |

---

## Architecture

### Phase 3: Alexa+ Integration & MCP Layer

```
User Voice / CLI
      │
      ▼
Alexa+ Simulator (app/alexa/simulator.py)
      │
      ▼
Alexa Adapter (app/alexa/adapter.py)
  - Intent classification (app/alexa/models.py)
  - Safety policy preservation
      │
      ▼
HomeOps MCP Client (app/mcp/client.py)
      │
      │ Streamable HTTP (http://host:8000/mcp)
      ▼
HomeOps MCP Server (app/mcp/server.py)
  │
  +--> HomeStateService     (app/services/home_state.py)
  │
  +--> IncidentEngine       (app/incidents/engine.py)
  │
  +--> SafetyPolicy         (app/safety/policy.py)
  │
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

## Running the Alexa+ Simulation & Demo (Phase 3)

The Alexa+ integration connects conversational voice interactions to the HomeOps MCP server and deterministic safety engine.

```bash
# Run the automated 11-step hackathon demo scenario:
python -m app.alexa.simulator --demo

# Run interactive voice prompt loop (REPL):
python -m app.alexa.simulator --interactive

# Pre-load a specific scenario:
python -m app.alexa.simulator --scenario water_hazard --interactive

# Connect to a standalone running Streamable HTTP server:
python -m app.alexa.simulator --mcp-url http://127.0.0.1:8000/mcp --demo
```

See [`docs/alexa.md`](docs/alexa.md) for full Alexa+ integration documentation.

---

## Running the Conversational Assistant Web UI (Phase 3.5)

HomeOps-AI includes an Alexa+-inspired conversational smart-home safety assistant web interface with progressive disclosure, deterministic safety guardrails, and real Streamable HTTP MCP integration.

```bash
# Start the unified web server & Streamable HTTP MCP server:
python -m uvicorn app.web.server:app --host 127.0.0.1 --port 8000

# Open in browser:
# http://127.0.0.1:8000
```

### Features & Experiences:
1. **Conversational Home Screen**: Prominent, calm natural conversation area with progressive disclosure and Web Speech API dictation.
2. **Home/Device Status**: Real-time connected sensor telemetry queried via `get_home_state`.
3. **Incident Investigation**: Deterministic correlation engine view with confidence gauge and rule firing.
4. **Event Timeline**: Interactive vertical chronological timeline marking correlated vs. background sensor events.
5. **Risk Assessment**: Deterministic 4-level risk matrix with strict policy rationale.
6. **Evidence & Explanation**: Step-by-step verified facts extracted by correlation rules.
7. **MCP Tool Activity & Results**: Real Streamable HTTP MCP tool execution audit log with JSON inspector.
8. **Recommended Response**: Actionable safe next steps.
9. **Physical-Action Safety Block**: Demonstrates deterministic safety policy blocking autonomous physical device actions.
10. **Persistent Incident History**: SQLite-backed incident audit store queried via MCP tools.
11. **MCP Connection Status**: Live `/mcp` health check, transport metrics, and tool registry.
12. **Responsive Mobile Experience**: Mobile-friendly layout with drawer navigation.

---

## Running Tests

```bash
# All tests (Phase 1 + Phase 2 + Phase 3 + Phase 3.5: 273 tests)
pytest -v tests/

# Phase 3 Alexa+ integration tests only (45 tests)
pytest -v tests/test_alexa_adapter.py tests/test_alexa_simulator.py

# Phase 2 MCP tests only (103 tests)
pytest -v tests/test_mcp_tools.py tests/test_mcp_registration.py

# Phase 1 deterministic core only (116 tests)
pytest -v tests/test_incident_engine.py tests/test_safety_policy.py
```

With coverage:

```bash
pytest -v --cov=app --cov-report=term-missing tests/
```

---

## Current Limitations

- **Simulated Alexa+ voice layer.** Because production Alexa+ Add-on access requires private Amazon developer credentials, voice transcription/synthesis is simulated via `app.alexa.simulator`. The MCP server, tools, incident engine, safety policy, and SQLite history are 100% real.
- **No real physical device execution.** In the current release, `execute_safe_action` always blocks autonomous device execution.
- **Incident history uses SQLite.** Zero-infrastructure local database; DynamoDB planned for future phases.
- **No LLM or AI inference.** All reasoning is deterministic rule-based logic (Bedrock planned for Phase 4).

---

## Planned Integrations (Phase 4+)

| Integration | Purpose | Status |
|---|---|---|
| **MCP** (Model Context Protocol) | Expose safe home-control tools to AI agents | ✅ Complete – Phase 2 |
| **Alexa+** | Voice-driven incident reporting and confirmation | ✅ Complete – Phase 3 |
| **Amazon Bedrock** | LLM-powered incident summarisation and Q&A | Planned – Phase 4 |
| **Strands Agents** | Multi-step AI orchestration for complex incidents | Planned – Phase 4 |
| **Real device APIs** | Ring, SmartThings, Home Assistant | Future |

---

## Project Structure

```
HomeOps-AI/
├── app/
│   ├── __init__.py
│   ├── main.py                     # CLI simulation runner
│   ├── config.py                   # Environment-variable configuration
│   ├── alexa/                      # Phase 3: Alexa+ integration layer
│   │   ├── __init__.py
│   │   ├── adapter.py              # AlexaAdapter (intent dispatch, speech, safety)
│   │   ├── models.py               # AlexaRequest, AlexaResponse, AlexaIntent
│   │   └── simulator.py            # AlexaSimulator (CLI REPL & 11-step demo)
│   ├── mcp/                        # Phase 2: MCP server & client
│   │   ├── __init__.py
│   │   ├── server.py               # MCPServer + Streamable HTTP + __main__
│   │   ├── client.py               # HomeOpsMCPClient (HTTP & in-process)
│   │   ├── tools.py                # 7 tool handler functions
│   │   └── context.py              # AppContext (dependency injection)
│   ├── agents/                     # Phase 4 stub: Strands/Bedrock
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
│   ├── test_incident_engine.py     # 56 Phase 1 engine tests
│   ├── test_safety_policy.py       # 60 Phase 1 safety policy tests
│   ├── test_mcp_tools.py           # 81 Phase 2 MCP tool tests
│   ├── test_mcp_registration.py    # 22 Phase 2 registration tests
│   ├── test_alexa_adapter.py       # 38 Phase 3 adapter tests
│   └── test_alexa_simulator.py     # 7 Phase 3 simulator tests
├── docs/
│   ├── architecture.md
│   ├── mcp.md                      # MCP tool reference
│   └── alexa.md                    # Alexa+ integration reference
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── LICENSE
```

---

## License

MIT — see [`LICENSE`](LICENSE).

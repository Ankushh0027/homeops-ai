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

## Architecture

```
Simulator JSON ──► HomeEvent (Pydantic) ──► IncidentEngine ──► Incident[]
                                                                    │
                                                                    ▼
                                                           evaluate_policy()
                                                                    │
                                                                    ▼
                                                            SafetyDecision
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

See [`docs/architecture.md`](docs/architecture.md) for a full component diagram.

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

## Running Tests

```bash
pytest -v tests/
```

With coverage:

```bash
pytest -v --cov=app --cov-report=term-missing tests/
```

---

## Current Limitations

- **No real device integration.** Events come from simulator JSON files only.
- **No persistence.** Incidents and decisions are in-memory only.
- **No notification delivery.** The system reports to stdout only.
- **No LLM or AI inference.** All reasoning is deterministic rule-based logic.
- **No web or API interface.** CLI only in the MVP.
- **Single-correlation pass.** The engine processes a batch of events once; it
  does not maintain state across time windows between invocations.

---

## Planned Integrations (Not Implemented)

| Integration | Purpose | Status |
|---|---|---|
| **MCP** (Model Context Protocol) | Expose safe home-control tools to AI agents | Planned – phase 2 |
| **Amazon Bedrock** | LLM-powered incident summarisation and Q&A | Planned – phase 2 |
| **Strands Agents** | Multi-step AI orchestration for complex incidents | Planned – phase 2 |
| **Alexa+** | Voice-driven incident reporting and confirmation | Planned – phase 3 |

These integrations are deliberately excluded from the MVP. The deterministic
engine must be production-ready and fully tested before any AI layer is added.

---

## Project Structure

```
HomeOps-AI/
├── app/
│   ├── __init__.py
│   ├── main.py           # CLI simulation runner
│   ├── config.py         # Environment-variable configuration
│   ├── mcp/              # MCP placeholder (not implemented)
│   ├── agents/           # Strands/Bedrock placeholder (not implemented)
│   ├── incidents/
│   │   ├── engine.py     # IncidentEngine
│   │   ├── rules.py      # Correlation rules
│   │   └── schemas.py    # Incident, Severity, IncidentType
│   ├── safety/
│   │   ├── policy.py     # evaluate_policy, execute_safe_action
│   │   └── schemas.py    # SafetyDecision, RiskLevel
│   ├── services/         # External service adapters (future)
│   └── models/
│       └── events.py     # HomeEvent Pydantic model
├── simulator/
│   ├── events/
│   │   └── sample_events.json
│   └── scenarios/
│       ├── security_incident.json
│       ├── water_hazard.json
│       └── leaving_home.json
├── tests/
│   ├── test_incident_engine.py
│   └── test_safety_policy.py
├── docs/
│   └── architecture.md
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── LICENSE
```

---

## License

MIT — see [`LICENSE`](LICENSE).

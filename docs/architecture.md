# HomeOps-AI Architecture

## Phase Status

| Phase | Status | Description |
|---|---|---|
| Phase 1 | ✅ Complete | Deterministic incident engine + safety policy + simulator |
| Phase 2 | ✅ Complete | MCP server with Streamable HTTP transport (7 tools) |
| Phase 3 | ✅ Complete | Alexa+ integration layer (Adapter, Simulator, MCP Client, Models) |
| Phase 4 | Planned | Strands agents, Amazon Bedrock LLM reasoning |

HomeOps-AI is a deterministic incident-response system for connected homes. It
correlates fragmented device events into meaningful incidents, assesses risk,
and recommends safe responses — all without making autonomous physical decisions.

```
+-------------------------------------------------------------------------+
|                          HomeOps-AI Phase 3                             |
+-------------------------------------------------------------------------+
|                                                                         |
|   User Voice Interaction / Simulator (app/alexa/simulator.py)           |
|              |                                                           |
|              v                                                           |
|   Alexa Adapter & Interaction Models (app/alexa/adapter.py, models.py)  |
|              |                                                           |
|              v                                                           |
|   HomeOps MCP Client (app/mcp/client.py)                                |
|              |  Streamable HTTP  (http://host:8000/mcp)                 |
|              v                                                           |
|   +----------------------------+                                        |
|   |  app/mcp/server.py         |  MCPServer (MCP SDK 2.2.0)            |
|   |  app/mcp/tools.py          |  7 tool handler adapters              |
|   |  app/mcp/context.py        |  AppContext (dependency injection)    |
|   +----------------------------+                                        |
|              |                                                           |
|              v                                                           |
|   +----------------------------+  +-----------------------------+       |
|   |  app/services/             |  |  app/models/events.py       |       |
|   |    home_state.py           |  |  HomeEvent (Pydantic v2)    |       |
|   |    incident_history.py     |  +-----------------------------+       |
|   |    (SQLite persistence)    |                                        |
|   +----------------------------+                                        |
|              |                                                           |
|              v                                                           |
|   +----------------------------+                                        |
|   |  app/incidents/            |                                        |
|   |    engine.py               |  IncidentEngine.process()             |
|   |    rules.py                |  rule_security_incident()             |
|   |                            |  rule_water_hazard()                  |
|   |                            |  rule_leaving_home()                  |
|   |    schemas.py              |  Incident, Severity, IncidentType     |
|   +----------------------------+                                        |
|              |                                                           |
|              v                                                           |
|   +----------------------------+                                        |
|   |  app/safety/               |                                        |
|   |    policy.py               |  evaluate_policy() -> SafetyDecision  |
|   |                            |  execute_safe_action() -> ALWAYS RAISES|
|   |    schemas.py              |  SafetyDecision, RiskLevel            |
|   +----------------------------+                                        |
|                                                                         |
|   +----------------------------+  +-----------------------------+       |
|   |  app/agents/ (stub)        |  |  app/mcp/context.py         |       |
|   |  Future: Strands/Bedrock   |  |  AppContext singleton        |       |
|   +----------------------------+  +-----------------------------+       |
+-------------------------------------------------------------------------+
```

## Phase 2 MCP Architecture

```
MCP Client
  |
  | Streamable HTTP (MCP SDK 2.2.0)
  |
  v
HomeOps MCP Server (app/mcp/server.py)
  |
  +--[Tool 1]--> get_home_state      --> HomeStateService
  +--[Tool 2]--> get_recent_events   --> HomeStateService
  +--[Tool 3]--> investigate_incident --> IncidentEngine + HomeStateService
  +--[Tool 4]--> assess_risk          --> evaluate_policy()
  +--[Tool 5]--> recommend_response   --> evaluate_policy()
  +--[Tool 6]--> execute_safe_action  --> ALWAYS BLOCKED (AutonomousActionForbiddenError)
  +--[Tool 7]--> record_incident      --> IncidentHistoryStore (SQLite)
```

### Why MCP is separated from business logic

MCP tool handlers (`tools.py`) are **thin adapters**. They:
- Sanitise and validate untrusted MCP input
- Delegate all reasoning to the deterministic core
- Return structured JSON responses

No business logic lives in the MCP layer. This means:
- The core can be tested without MCP
- The MCP layer can be replaced (e.g. REST, gRPC) without touching the engine
- Future agent frameworks (Strands, Bedrock) can use the same tool handlers


└─────────────────────────────────────────────────────────────────────────┘
```

## Component Descriptions

### `app/models/events.py`
Pydantic v2 `HomeEvent` model. Validates all incoming events at the boundary.
Unknown device types and event types are rejected immediately. No invalid data
can enter the engine.

### `app/incidents/rules.py`
Three pure rule functions — one per supported scenario:

| Rule | Trigger | Severity escalation |
|---|---|---|
| `rule_security_incident` | `door_sensor:opened` | + motion → HIGH; + occupancy → LOW |
| `rule_water_hazard` | `water_sensor:moisture_detected` | + appliance → HIGH; + rising → CRITICAL |
| `rule_leaving_home` | `occupancy_sensor:user_departing` | + open door → HIGH; + issues → MEDIUM |

Each rule computes confidence explicitly from named evidence signals and caps
partial-evidence confidence at 0.85. Rules never claim certainty.

### `app/incidents/engine.py`
`IncidentEngine.process(events)` — stateless, deterministic. Sorts events by
timestamp, executes all rules in priority order, filters below the configured
minimum confidence, and returns incidents sorted by descending severity.

### `app/safety/policy.py`
`evaluate_policy(incident)` maps severity to a structured `SafetyDecision`.
The policy table is explicit and auditable:

| Risk level | Action permitted? | Requires confirmation? | Requires approval? | Escalation? |
|---|---|---|---|---|
| LOW | ✅ (informational) | ❌ | ❌ | ❌ |
| MEDIUM | ❌ | ✅ | ❌ | ❌ |
| HIGH | ❌ | ✅ | ✅ | ❌ |
| CRITICAL | ❌ | ✅ | ✅ | ✅ |

`execute_safe_action()` **always raises `AutonomousActionForbiddenError`** in
the MVP. This is intentional. No code path may trigger device actions without a
full human-in-the-loop approval flow (future phase).

### `simulator/`
JSON scenario files that produce realistic event sequences for each supported
scenario. `app/main.py` loads these and feeds them through the full pipeline.

## Data Flow

```
JSON scenario → HomeEvent[] → IncidentEngine → Incident[] → evaluate_policy → SafetyDecision
```

## Design Principles

1. **Determinism first** — every decision is reproducible given the same input.
2. **Safety by default** — physical actions are prohibited unless proven safe.
3. **Auditability** — every incident includes an evidence trail; every decision
   includes an audit trail.
4. **Separation of concerns** — models, rules, engine, policy, and services are
   in distinct modules.
5. **No premature abstraction** — rules are module-level functions, not
   class hierarchies.
6. **No secrets in code** — all configuration comes from environment variables.

## Integration Points

| Integration | Package | Status |
|---|---|---|
| MCP (Model Context Protocol) | `app/mcp/` | ✅ Complete (Phase 2) |
| Alexa+ Integration Layer | `app/alexa/` | ✅ Complete (Phase 3) |
| Strands agents | `app/agents/` | Planned (Phase 4) |
| Amazon Bedrock LLM | `app/agents/` | Planned (Phase 4) |

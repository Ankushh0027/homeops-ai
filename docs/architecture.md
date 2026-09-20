# HomeOps-AI Architecture

## Overview

HomeOps-AI is a deterministic incident-response system for connected homes. It
correlates fragmented device events into meaningful incidents, assesses risk,
and recommends safe responses — all without making autonomous physical decisions.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          HomeOps-AI MVP                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Simulator / Real Events                                               │
│   ┌───────────────────────┐                                             │
│   │  simulator/scenarios/ │  JSON event sequences                       │
│   │  simulator/events/    │  ad-hoc sample events                       │
│   └──────────┬────────────┘                                             │
│              │ List[HomeEvent]                                           │
│              ▼                                                           │
│   ┌───────────────────────┐                                             │
│   │  app/models/events.py │  Pydantic-validated typed models            │
│   └──────────┬────────────┘                                             │
│              │ List[HomeEvent]                                           │
│              ▼                                                           │
│   ┌───────────────────────┐                                             │
│   │  app/incidents/       │                                             │
│   │    engine.py          │  IncidentEngine.process()                   │
│   │    rules.py           │  rule_security_incident()                   │
│   │                       │  rule_water_hazard()                        │
│   │                       │  rule_leaving_home()                        │
│   │    schemas.py         │  Incident, Severity, IncidentType           │
│   └──────────┬────────────┘                                             │
│              │ List[Incident]                                            │
│              ▼                                                           │
│   ┌───────────────────────┐                                             │
│   │  app/safety/          │                                             │
│   │    policy.py          │  evaluate_policy() → SafetyDecision         │
│   │                       │  execute_safe_action() → ALWAYS RAISES      │
│   │    schemas.py         │  SafetyDecision, RiskLevel, ActionPermission│
│   └──────────┬────────────┘                                             │
│              │ SafetyDecision                                            │
│              ▼                                                           │
│   ┌───────────────────────┐                                             │
│   │  app/main.py          │  CLI report output (human-readable)         │
│   └───────────────────────┘                                             │
│                                                                         │
│   ┌───────────────────────┐  ┌──────────────────────────────────────┐  │
│   │  app/mcp/             │  │  app/agents/                         │  │
│   │  (placeholder)        │  │  (placeholder)                       │  │
│   │  Future: MCP tools    │  │  Future: Strands/Bedrock agents      │  │
│   └───────────────────────┘  └──────────────────────────────────────┘  │
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

## Future Integration Points

| Integration | Package | Status |
|---|---|---|
| MCP (Model Context Protocol) | `app/mcp/` | Placeholder – not implemented |
| Strands agents | `app/agents/` | Placeholder – not implemented |
| Amazon Bedrock LLM | `app/agents/` | Placeholder – not implemented |
| Alexa+ | (TBD) | Not started |

# HomeOps MCP Server – Developer Reference

## Overview

HomeOps-AI exposes its deterministic incident-response capabilities as an
**MCP (Model Context Protocol) server** over **Streamable HTTP** transport.

This document describes how to start the server, the available tools, their
inputs and outputs, and how to test locally.

---

## Server Startup

```bash
# Default: binds to 127.0.0.1:8000
python -m app.mcp.server

# Custom host/port
python -m app.mcp.server --host 0.0.0.0 --port 8080

# Pre-load a simulator scenario on startup
python -m app.mcp.server --load-scenario security_incident

# Environment variable overrides
MCP_HOST=0.0.0.0 MCP_PORT=8080 python -m app.mcp.server
```

The MCP endpoint is: `http://<host>:<port>/mcp`

---

## Transport

**Streamable HTTP** (MCP SDK 2.2.0+).

This is the modern, cloud-native MCP transport that consolidates protocol
communication into a single HTTP endpoint.  It is required for the planned
Alexa+ integration track.

The server can also be mounted as a standalone ASGI application:

```bash
# Via uvicorn
uvicorn app.mcp.server:http_app --host 0.0.0.0 --port 8000
```

---

## Available Tools

### 1. `get_home_state`

Return the current simulated connected-home state.

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `location` | string | No | Filter snapshot by location label |

**Example response:**
```json
{
  "home_id": "demo-home-001",
  "snapshot_at": "2026-09-20T07:00:00Z",
  "loaded_scenario": "security_incident",
  "total_events_logged": 3,
  "devices": [
    {
      "device_id": "door-back-01",
      "device_type": "door_sensor",
      "location": "back_door",
      "last_event_type": "opened",
      "last_seen": "2026-09-20T02:15:00Z",
      "last_value": null
    }
  ],
  "active_conditions": [],
  "occupancy": {
    "person_detected": false,
    "user_departing": false,
    "occupancy_sensors_count": 0
  }
}
```

---

### 2. `get_recent_events`

Retrieve recent home sensor events.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | No | 50 | Max events to return (clamped to 1–200) |
| `location` | string | No | — | Filter by location |
| `device_type` | string | No | — | Filter by device type |
| `event_type` | string | No | — | Filter by event type |

**Example response:**
```json
{
  "total": 2,
  "limit_applied": 50,
  "filters": { "location": "back_door" },
  "events": [
    {
      "event_id": "sec-001",
      "timestamp": "2026-09-20T02:15:00Z",
      "device_id": "door-back-01",
      "device_type": "door_sensor",
      "event_type": "opened",
      "location": "back_door",
      "value": null,
      "metadata": {}
    }
  ]
}
```

---

### 3. `investigate_incident`

Run the deterministic incident correlation engine.

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `scenario` | string | No | Named scenario: `security_incident`, `water_hazard`, `leaving_home` |
| `raw_events` | list[dict] | No | Raw event dicts to validate and inject (max 100) |

**Example response:**
```json
{
  "event_count": 3,
  "incident_count": 1,
  "validation_errors": [],
  "incidents": [
    {
      "incident_id": "uuid...",
      "incident_type": "SECURITY",
      "severity": "HIGH",
      "title": "Unverified Entry Detected",
      "summary": "...",
      "evidence": ["door_sensor 'door-back-01' reported 'opened'..."],
      "confidence": 0.85,
      "recommended_next_step": "...",
      "created_at": "2026-09-20T07:00:00Z"
    }
  ]
}
```

---

### 4. `assess_risk`

Evaluate the deterministic safety policy for a described incident.

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `incident_type` | string | Yes | `SECURITY`, `WATER_HAZARD`, `LEAVING_HOME`, `UNKNOWN` |
| `severity` | string | Yes | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `confidence` | float | Yes | Confidence in [0.0, 1.0] |
| `title` | string | No | Incident title |
| `summary` | string | No | Incident summary |
| `evidence` | list[str] | No | Evidence items |
| `recommended_next_step` | string | No | Recommended action |

**Example response:**
```json
{
  "incident_id": "uuid...",
  "risk_level": "HIGH",
  "action_permission": "REQUIRES_EXPLICIT_APPROVAL",
  "action_permitted": false,
  "requires_user_confirmation": true,
  "requires_explicit_approval": true,
  "escalation_required": false,
  "allowed_actions": ["Review camera footage...", "..."],
  "policy_rationale": "Risk level is HIGH...",
  "audit_trail": ["[2026-09-20T07:00:00Z] evaluate_policy called..."]
}
```

---

### 5. `recommend_response`

Return a safe response recommendation (informational only, no physical action).

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `incident_type` | string | Yes | Incident type |
| `severity` | string | Yes | Severity level |
| `confidence` | float | Yes | Confidence [0.0, 1.0] |
| `context` | string | No | Optional free-text context |

**Example response:**
```json
{
  "risk_level": "HIGH",
  "requires_confirmation": true,
  "requires_explicit_approval": true,
  "escalation_required": false,
  "recommended_action": "Review camera footage for the affected entry point.",
  "all_safe_actions": ["..."],
  "reason": "Risk level is HIGH...",
  "physical_action_executed": false,
  "note": "This is a recommendation only. HomeOps will never execute a physical action automatically."
}
```

---

### 6. `execute_safe_action`

> ⚠️ **This tool always returns `"executed": false` in the current MVP.**
>
> Physical device actions are structurally prohibited. This tool exists as
> a well-defined action boundary for future agent integrations.

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `action_name` | string | Yes | Requested action name |
| `device_id` | string | No | Target device ID |

**Response (always):**
```json
{
  "executed": false,
  "status": "blocked",
  "action_name": "arm_security_system",
  "device_id": null,
  "reason": "Physical device execution is disabled in the current MVP..."
}
```

---

### 7. `record_incident`

Record an investigated incident to the local SQLite audit history store.

**Input parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `incident_type` | string | Yes | Incident type |
| `severity` | string | Yes | Severity |
| `confidence` | float | Yes | Confidence [0.0, 1.0] |
| `title` | string | Yes | Incident title |
| `summary` | string | Yes | Incident summary |
| `evidence` | list[str] | Yes | Evidence list |
| `recommended_next_step` | string | Yes | Recommendation |

**Example response:**
```json
{
  "recorded": true,
  "incident_id": "uuid...",
  "severity": "HIGH",
  "risk_level": "HIGH",
  "message": "Incident uuid... successfully recorded to audit history."
}
```

---

## Safety Restrictions

1. **No physical device actions** are ever executed.  `execute_safe_action` always returns blocked.
2. **All inputs are validated** before reaching the core engine.
3. **Safety policy is always consulted** before recording or recommending.
4. **MCP input is treated as untrusted** – all strings are sanitised and length-capped.
5. The only valid flow is:
   ```
   MCP request → validated tool → application logic → deterministic safety policy
   → allowed simulated operation OR blocked action
   ```

---

## Local Testing

### Unit tests (no server required)

```bash
pytest -v tests/test_mcp_tools.py tests/test_mcp_registration.py
```

### Full test suite

```bash
pytest -v tests/
```

### Manual server interaction

Start the server:
```bash
python -m app.mcp.server --load-scenario security_incident
```

The server listens at `http://127.0.0.1:8000/mcp`.

Use the MCP CLI inspector or any MCP-compatible client to call tools.

---

## Not Implemented

| Integration | Status |
|---|---|
| Alexa+ | Not implemented – planned Phase 3 |
| Strands agents | Not implemented – planned Phase 3 |
| Amazon Bedrock | Not implemented – planned Phase 3 |
| DynamoDB persistence | Not implemented – SQLite used in MVP |
| Real device APIs | Not implemented – simulator only |

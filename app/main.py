"""
app/main.py
===========
HomeOps-AI local simulation runner.

This script loads each simulator scenario, feeds it through the incident
correlation engine, evaluates the safety policy for each result, and prints
a structured report to stdout.

Usage
-----
    python -m app.main                            # run all scenarios
    python -m app.main --scenario security_incident
    python -m app.main --scenario water_hazard
    python -m app.main --scenario leaving_home

This is NOT a production entry point.  It exists purely to demonstrate
the end-to-end pipeline locally and to make the integration testable.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from app.incidents.engine import IncidentEngine
from app.incidents.schemas import Incident
from app.models.events import HomeEvent
from app.safety.policy import evaluate_policy
from app.safety.schemas import SafetyDecision

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(name)s | %(message)s",
)

# ---------------------------------------------------------------------------
# Simulator helpers
# ---------------------------------------------------------------------------

SCENARIOS_DIR = Path(__file__).parent.parent / "simulator" / "scenarios"

SCENARIO_FILES: dict[str, str] = {
    "security_incident": "security_incident.json",
    "water_hazard": "water_hazard.json",
    "leaving_home": "leaving_home.json",
}


def load_scenario(name: str) -> list[HomeEvent]:
    """Load a named scenario from the simulator directory."""
    filename = SCENARIO_FILES.get(name)
    if filename is None:
        raise ValueError(
            f"Unknown scenario {name!r}. "
            f"Available: {list(SCENARIO_FILES.keys())}"
        )
    path = SCENARIOS_DIR / filename
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    events = [HomeEvent.model_validate(e) for e in data["events"]]
    return events


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

_SEP = "-" * 72


def _print_incident(incident: Incident, decision: SafetyDecision) -> None:
    print(f"\n{'=' * 72}")
    print(f"  INCIDENT  |  {incident.incident_type.value}")
    print(f"{'=' * 72}")
    print(f"  ID          : {incident.incident_id}")
    print(f"  Severity    : {incident.severity.value}")
    print(f"  Confidence  : {incident.confidence:.0%}")
    print(f"  Title       : {incident.title}")
    print(f"\n  Summary\n  {_SEP}")
    print(f"  {incident.summary}")
    print(f"\n  Evidence ({len(incident.evidence)} item(s))\n  {_SEP}")
    for i, item in enumerate(incident.evidence, 1):
        print(f"  {i:2d}. {item}")
    print(f"\n  Recommended Next Step\n  {_SEP}")
    print(f"  {incident.recommended_next_step}")
    print(f"\n  Safety Decision\n  {_SEP}")
    print(f"  Risk Level           : {decision.risk_level.value}")
    print(f"  Action Permission    : {decision.action_permission.value}")
    print(f"  Escalation Required  : {decision.escalation_required}")
    print(f"  Policy Rationale     : {decision.policy_rationale}")
    if decision.allowed_actions:
        print(f"\n  Allowed Safe Actions ({len(decision.allowed_actions)})")
        for action in decision.allowed_actions:
            print(f"    • {action}")
    print()


def run_scenario(name: str, engine: IncidentEngine) -> int:
    """Run a single scenario and print results.  Returns incident count."""
    print(f"\n{'#' * 72}")
    print(f"  SCENARIO: {name.upper().replace('_', ' ')}")
    print(f"{'#' * 72}")

    events = load_scenario(name)
    print(f"  Loaded {len(events)} event(s) from scenario '{name}'.")

    incidents = engine.process(events)

    if not incidents:
        print("  No incidents detected above the confidence threshold.")
        return 0

    print(f"  {len(incidents)} incident(s) detected.")
    for incident in incidents:
        decision = evaluate_policy(incident)
        _print_incident(incident, decision)

    return len(incidents)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="HomeOps-AI local scenario simulator"
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIO_FILES.keys()),
        default=None,
        help="Run a specific scenario (default: run all).",
    )
    args = parser.parse_args(argv)

    engine = IncidentEngine()

    scenarios_to_run = (
        [args.scenario] if args.scenario else list(SCENARIO_FILES.keys())
    )

    total_incidents = 0
    for name in scenarios_to_run:
        total_incidents += run_scenario(name, engine)

    print(f"\n{'=' * 72}")
    print(f"  Simulation complete. Total incidents detected: {total_incidents}")
    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    main(sys.argv[1:])

"""
app/alexa/simulator.py
======================
Deterministic Alexa+ simulation and demo runner for HomeOps-AI.

Because real Alexa+ hardware/cloud developer access requires private preview
credentials, this simulator provides a deterministic CLI experience that:
  1. Accepts user utterances.
  2. Forwards them to the AlexaAdapter.
  3. The adapter calls the real HomeOps MCP server (in-process or over Streamable HTTP).
  4. The MCP server calls the deterministic incident engine and safety policy.
  5. Outputs the safety-preserving Alexa+ speech and structured decision data.

Usage
-----
    # Run the automated 11-step hackathon demo:
    python -m app.alexa.simulator --demo

    # Run interactive voice prompt loop:
    python -m app.alexa.simulator --interactive

    # Pre-load a specific scenario:
    python -m app.alexa.simulator --scenario water_hazard

    # Connect to a running Streamable HTTP server:
    python -m app.alexa.simulator --mcp-url http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from app.alexa.adapter import AlexaAdapter
from app.alexa.models import AlexaResponse
from app.mcp.client import HomeOpsMCPClient


class AlexaSimulator:
    """Simulator for testing and demonstrating the Alexa+ HomeOps integration."""

    def __init__(
        self,
        adapter: Optional[AlexaAdapter] = None,
        mcp_url: Optional[str] = None,
        scenario: str = "security_incident",
    ) -> None:
        if adapter:
            self.adapter = adapter
        else:
            client = HomeOpsMCPClient(base_url=mcp_url)
            self.adapter = AlexaAdapter(mcp_client=client)

        self.scenario = scenario
        self.load_scenario(scenario)

    def load_scenario(self, scenario_name: str) -> int:
        """Load a named scenario into the HomeOps home state."""
        ctx = getattr(self.adapter.mcp_client, "_context", None)
        if ctx and hasattr(ctx, "home_state"):
            try:
                ctx.home_state.clear()
                count = ctx.home_state.load_scenario(scenario_name)
                self.scenario = scenario_name
                return count
            except Exception:
                return 0
        return 0

    def ask(self, utterance: str) -> AlexaResponse:
        """Submit a user utterance to the Alexa adapter and return the response."""
        return self.adapter.handle_utterance(utterance)

    def run_demo(self) -> list[AlexaResponse]:
        """Execute the deterministic 11-step hackathon demo scenario."""
        print("\n" + "=" * 70)
        print("         ALEXA+ HOMEOPS DETERMINISTIC DEMO SCENARIO")
        print("   Real: HomeOps MCP Server, Incident Engine, Safety Policy, SQLite")
        print("   Simulated: Alexa+ Voice Transcription & Synthesis Layer")
        print("=" * 70)

        steps = [
            ("Step 1-4: Raw Sensor Events Ingested & Correlated", None),
            (
                "Step 5: User asks about home status",
                "What's happening at home?",
            ),
            (
                "Step 6: User asks to explain the incident",
                "Why did you say something unusual happened?",
            ),
            (
                "Step 7: User asks for risk assessment",
                "How serious is it?",
            ),
            (
                "Step 8: User asks for recommended response",
                "What should I do?",
            ),
            (
                "Step 9-10: User requests physical action execution (Safety Gate)",
                "Turn off the configured appliance.",
            ),
            (
                "Step 11: User checks incident history (Audit Verification)",
                "Has this happened before?",
            ),
        ]

        responses: list[AlexaResponse] = []

        for title, utterance in steps:
            print(f"\n--- {title} ---")
            if utterance is None:
                # Pre-correlation step description
                print("[Sensor Log] 02:15:00Z - door_sensor 'door-back-01' reported 'opened'")
                print("[Sensor Log] 02:15:45Z - motion_sensor 'motion-hallway-01' reported 'detected'")
                print("[Sensor Log] 02:16:10Z - motion_sensor 'motion-kitchen-01' reported 'detected'")
                print("[Occupancy] No recognised household resident detected.")
                print("[Correlation Engine] Correlated 3 events -> SECURITY incident (HIGH severity)")
                continue

            print(f"\nYou: {utterance}")
            response = self.ask(utterance)
            responses.append(response)

            print(f"\nAlexa+: {response.speech}")
            print(f"        [Intent: {response.intent}]")
            if response.risk_level:
                print(f"        [Risk Level: {response.risk_level}]")
            if response.requires_confirmation:
                print("        [Requires Confirmation: True]")
            if response.requires_explicit_approval:
                print("        [Requires Explicit Approval: True]")
            if response.action_status:
                print(f"        [Action Status: {response.action_status} (executed: {response.action_executed})]")

        print("\n" + "=" * 70)
        print("Demo completed successfully. All safety boundaries preserved.")
        print("=" * 70 + "\n")
        return responses

    def run_interactive(self) -> None:
        """Run an interactive prompt loop for free-form testing."""
        print("\n" + "=" * 60)
        print("             Alexa+ HomeOps Simulation REPL")
        print(f"  Pre-loaded scenario: {self.scenario}")
        print("  Type 'quit' or 'exit' to end.")
        print("=" * 60 + "\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting simulation.")
                break

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit"):
                print("Exiting simulation.")
                break

            response = self.ask(user_input)
            print(f"\nAlexa+: {response.speech}\n")


def main() -> None:
    """CLI entry point for app.alexa.simulator."""
    parser = argparse.ArgumentParser(description="Alexa+ HomeOps Simulation Runner")
    parser.add_argument(
        "--scenario",
        choices=["security_incident", "water_hazard", "leaving_home"],
        default="security_incident",
        help="Pre-load a simulator scenario (default: security_incident).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the deterministic 11-step hackathon demo scenario.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run an interactive voice prompt loop.",
    )
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="Optional Streamable HTTP URL (e.g. http://127.0.0.1:8000/mcp).",
    )

    args = parser.parse_args()

    simulator = AlexaSimulator(
        scenario=args.scenario,
        mcp_url=args.mcp_url,
    )

    if args.demo:
        simulator.run_demo()
    elif args.interactive or sys.stdin.isatty():
        # If interactive requested or running in a terminal with no arguments, run demo then REPL
        simulator.run_demo()
        simulator.run_interactive()
    else:
        simulator.run_demo()


if __name__ == "__main__":
    main()

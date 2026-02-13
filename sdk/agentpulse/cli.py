"""AgentPulse CLI — diagnostic and testing commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def cmd_status(args: argparse.Namespace) -> None:
    """Check AgentPulse configuration and connectivity."""
    api_key = os.environ.get("AGENTPULSE_API_KEY", "")
    endpoint = os.environ.get("AGENTPULSE_ENDPOINT", "https://api.agentpulse.dev")
    agent = os.environ.get("AGENTPULSE_AGENT", "")

    print("AgentPulse SDK Status")
    print("=" * 40)
    print(f"  Endpoint:  {endpoint}")
    print(f"  API Key:   {'***' + api_key[-4:] if len(api_key) > 4 else '(not set)'}")
    print(f"  Agent:     {agent or '(auto-detect)'}")
    print(f"  Enabled:   {os.environ.get('AGENTPULSE_ENABLED', 'true')}")
    print(f"  Debug:     {os.environ.get('AGENTPULSE_DEBUG', 'false')}")

    # Check connectivity
    import urllib.request
    import urllib.error

    print()
    try:
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/health",
            headers={"User-Agent": "agentpulse-cli/0.1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"  API:       ✓ reachable (HTTP {resp.status})")
    except Exception as exc:
        print(f"  API:       ✗ unreachable ({exc})")

    # Check for LLM libraries
    print()
    print("Detected Libraries:")
    for lib in ("openai", "anthropic", "litellm", "langchain", "langchain_core"):
        try:
            mod = __import__(lib)
            ver = getattr(mod, "__version__", "?")
            print(f"  {lib}: {ver}")
        except ImportError:
            print(f"  {lib}: not installed")


def cmd_test(args: argparse.Namespace) -> None:
    """Send a test event to verify connectivity."""
    import agentpulse

    client = agentpulse.init()
    client.event("cli_test", {"message": "Test event from agentpulse CLI", "ts": time.time()})
    client.flush()
    print("✓ Test event sent")
    agentpulse.shutdown()


def cmd_costs(args: argparse.Namespace) -> None:
    """Print the built-in cost table."""
    from agentpulse.costs import COST_TABLE

    print(f"{'Model':<30} {'Input/1K':>10} {'Output/1K':>10}")
    print("-" * 52)
    for model, (inp, out) in sorted(COST_TABLE.items()):
        print(f"{model:<30} ${inp:<9.6f} ${out:<9.6f}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentpulse", description="AgentPulse CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Check configuration and connectivity")
    sub.add_parser("test", help="Send a test event")
    sub.add_parser("costs", help="Print cost table")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "costs":
        cmd_costs(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

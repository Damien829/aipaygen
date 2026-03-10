"""AiPayGen Agent CLI — pay-per-call AI tools via x402."""

import argparse
import json
import os
import sys

import requests
from eth_account import Account
from x402.client import create_x402_session

API_BASE = os.environ.get("AIPAYGEN_API_URL", "https://api.aipaygen.com")


def _get_session() -> requests.Session:
    """Create an x402-wrapped requests session using AGENT_PRIVATE_KEY."""
    private_key = os.environ.get("AGENT_PRIVATE_KEY")
    if not private_key:
        print("Error: AGENT_PRIVATE_KEY environment variable is not set.", file=sys.stderr)
        print("Export a hex private key for a Base-funded wallet:", file=sys.stderr)
        print("  export AGENT_PRIVATE_KEY=0xabc123...", file=sys.stderr)
        sys.exit(1)
    return create_x402_session(private_key)


def _call(session: requests.Session, endpoint: str, data: dict) -> dict:
    """POST to an AiPayGen endpoint, returning the JSON response."""
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    try:
        resp = session.post(url, json=data)
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    cost = resp.headers.get("X-Payment-Amount")

    if resp.status_code == 200:
        result = resp.json()
        if cost:
            print(f"[paid {cost}]", file=sys.stderr)
        return result
    elif resp.status_code == 402:
        print("Payment required but x402 negotiation failed.", file=sys.stderr)
        print(f"Response: {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"HTTP {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)


# ── Subcommands ──────────────────────────────────────────────────────────


def cmd_ask(args):
    """Ask a question."""
    session = _get_session()
    result = _call(session, "/ask", {"question": args.question})
    print(result.get("answer", json.dumps(result, indent=2)))


def cmd_research(args):
    """Research a topic."""
    session = _get_session()
    result = _call(session, "/research", {"topic": args.topic, "depth": args.depth})
    print(json.dumps(result, indent=2))


def cmd_translate(args):
    """Translate text."""
    session = _get_session()
    result = _call(session, "/translate", {"text": args.text, "to": args.to})
    print(result.get("translated", json.dumps(result, indent=2)))


def cmd_summarize(args):
    """Summarize text (accepts argument or stdin)."""
    text = args.text
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        print("Error: provide text as an argument or pipe via stdin.", file=sys.stderr)
        sys.exit(1)
    session = _get_session()
    result = _call(session, "/summarize", {"text": text, "style": args.style})
    print(result.get("summary", json.dumps(result, indent=2)))


def cmd_balance(args):
    """Show wallet address and balance hint."""
    private_key = os.environ.get("AGENT_PRIVATE_KEY")
    if not private_key:
        print("Error: AGENT_PRIVATE_KEY not set.", file=sys.stderr)
        sys.exit(1)
    acct = Account.from_key(private_key)
    print(f"Wallet address: {acct.address}")
    print(f"Check your balance at: https://basescan.org/address/{acct.address}")


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="aipaygen-agent",
        description="CLI agent that pays for AiPayGen API calls via x402",
    )
    sub = parser.add_subparsers(dest="command")

    # ask
    p_ask = sub.add_parser("ask", help="Ask a question")
    p_ask.add_argument("question", help="The question to ask")
    p_ask.set_defaults(func=cmd_ask)

    # research
    p_research = sub.add_parser("research", help="Research a topic")
    p_research.add_argument("topic", help="Topic to research")
    p_research.add_argument("--depth", default="quick", choices=["quick", "deep"], help="Research depth")
    p_research.set_defaults(func=cmd_research)

    # translate
    p_translate = sub.add_parser("translate", help="Translate text")
    p_translate.add_argument("text", help="Text to translate")
    p_translate.add_argument("--to", default="French", help="Target language (default: French)")
    p_translate.set_defaults(func=cmd_translate)

    # summarize
    p_summarize = sub.add_parser("summarize", help="Summarize text")
    p_summarize.add_argument("text", nargs="?", default=None, help="Text to summarize (or pipe via stdin)")
    p_summarize.add_argument("--style", default="bullet_points", help="Summary style (default: bullet_points)")
    p_summarize.set_defaults(func=cmd_summarize)

    # balance
    p_balance = sub.add_parser("balance", help="Show wallet address")
    p_balance.set_defaults(func=cmd_balance)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()

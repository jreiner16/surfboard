"""surfboard CLI — headless commands: setup, status, log, help."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from integrations import setup as wizard

HISTORY_FILE = Path.home() / ".surfboard" / "history.jsonl"

TOOLS = [
    "Claude Desktop",
    "Cursor",
    "OpenCode",
    "VS Code (GitHub Copilot)",
    "Windsurf",
    "Claude Code (CLI)",
]


def load_history(n: int = 50) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in reversed(lines[-n * 2:]):
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(entries[-n:]))


def cmd_status(args: argparse.Namespace) -> None:
    entries = load_history(200)
    total = len(entries)
    ok = sum(1 for e in entries if e.get("status") == "ok")
    pct = f"{int(ok / max(total, 1) * 100)}%"

    n_configured = sum(1 for t in TOOLS if wizard.check_tool_status(t))

    print(f"Surfboard v0.1.0")
    print(f"Tools configured: {n_configured}/{len(TOOLS)}")
    if total:
        print(f"History: {total} entries ({ok} ok, {pct} success)")
    else:
        print(f"History: no activity yet")


def cmd_log(args: argparse.Namespace) -> None:
    n = args.n or 50
    entries = load_history(n)
    if not entries:
        print("No history yet.")
        return

    if args.tail:
        import time
        try:
            while True:
                os.system("cls" if os.name == "nt" else "clear")
                _print_log_entries(entries[:n])
                time.sleep(2)
        except KeyboardInterrupt:
            pass
    else:
        _print_log_entries(entries[:n])


def _print_log_entries(entries: list[dict]) -> None:
    for i, e in enumerate(entries):
        try:
            ts = datetime.fromisoformat(e["ts"]).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts = "???"
        tool = e.get("tool", "")
        detail = e.get("detail", "")[:100]
        status = e.get("status", "")
        ok_mark = "OK" if status == "ok" else "FAIL"
        print(f"{ts}  [{ok_mark}] {tool:<12} {detail}")


def cmd_setup(args: argparse.Namespace) -> None:
    wizard.main()


def cmd_help(args: argparse.Namespace) -> None:
    print("Usage: surfboard <command>")
    print()
    print("Commands:")
    print("  setup     Run the interactive setup wizard")
    print("  status    Show current Surfboard status")
    print("  log       Show browsing history")
    print("  help      Show this help message")
    print()
    print("Flags:")
    print("  surfboard log [-n N]       Show last N entries (default: 50)")
    print("  surfboard log --tail       Tail history in real-time")
    print()
    print("Aliases:")
    print("  surfboard-install          Interactive setup wizard (standalone)")
    print("  surfboard-post-install     Silent auto-registration")
    print("  surfboard-mcp              Start MCP server (stdin/stdout)")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="surfboard",
        description="Human-quality web browsing for AI agents",
        add_help=False,
    )
    parser.add_argument("command", nargs="?", default="help",
                        choices=["setup", "status", "log", "help"])
    parser.add_argument("-n", type=int, default=50, help="Number of log entries")
    parser.add_argument("--tail", action="store_true", help="Tail log in real-time")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "log":
        cmd_log(args)
    else:
        cmd_help(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())

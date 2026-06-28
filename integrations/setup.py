"""Surfboard install wizard - configures MCP for common AI coding tools."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _server_command() -> tuple[str, list[str]]:
    """Return (command, args) for the MCP server, preferring the installed console script."""
    if shutil.which("surfboard-mcp"):
        return "surfboard-mcp", []
    script = Path(__file__).parent.parent / "mcp_server.py"
    return sys.executable, [str(script)]


def ensure_playwright_browser() -> None:
    """Install Playwright's Chromium browser if it is not already available."""
    try:
        import playwright
    except Exception:
        raise RuntimeError("Playwright is not installed. Install the package first with pip install -e .")

    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to install Playwright Chromium: {exc.stdout or exc}") from exc


TOOLS = {
    "1": "Claude Desktop",
    "2": "Cursor",
    "3": "OpenCode",
    "4": "VS Code (GitHub Copilot)",
    "5": "Windsurf",
    "6": "Claude Code (CLI)",
}

_TOOL_ORDER = ["1", "2", "3", "4", "5", "6"]


def _config_paths() -> dict[str, Path]:
    home = Path.home()
    system = sys.platform

    if system == "win32":
        claude_dir = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Claude"
    elif system == "darwin":
        claude_dir = home / "Library" / "Application Support" / "Claude"
    else:
        claude_dir = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "Claude"

    return {
        "Claude Desktop": claude_dir / "claude_desktop_config.json",
        "Cursor": home / ".cursor" / "mcp.json",
        "OpenCode": home / ".config" / "opencode" / "opencode.json",
        "VS Code (GitHub Copilot)": home / ".vscode" / "mcp.json",
        "Windsurf": home / ".codeium" / "windsurf" / "mcp_config.json",
        "Claude Code (CLI)": home / ".claude.json",
    }


def _build_entry(tool: str, command: str, args: list[str]) -> tuple[str, dict]:
    if tool == "OpenCode":
        return "mcp", {
            "type": "local",
            "command": [command] + args,
            "enabled": True,
        }
    return "mcpServers", {
        "command": command,
        "args": args,
    }


def _install(tool: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    command, args = _server_command()
    key, entry = _build_entry(tool, command, args)

    if key not in existing:
        existing[key] = {}
    existing[key]["surfboard"] = entry
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def install_tool(name: str) -> str:
    """Install Surfboard for a single tool by display name. Returns status message."""
    paths = _config_paths()
    if name not in paths:
        return f"Unknown tool: {name}"
    try:
        ensure_playwright_browser()
        _install(name, paths[name])
        return f"OK  {name}"
    except Exception as e:
        return f"ERR {name}: {e}"


def check_tool_status(name: str) -> bool:
    """Check if a tool has Surfboard registered in its config."""
    paths = _config_paths()
    path = paths.get(name)
    if not path or not path.exists():
        return False
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        key = "mcp" if name == "OpenCode" else "mcpServers"
        return "surfboard" in cfg.get(key, {})
    except Exception:
        return False


def tool_path(name: str) -> Path | None:
    return _config_paths().get(name)


def tools_and_paths() -> list[tuple[str, Path]]:
    """Return sorted list of (tool_name, config_path) tuples."""
    paths = _config_paths()
    return [(TOOLS[k], paths[TOOLS[k]]) for k in _TOOL_ORDER]


def auto_install() -> None:
    """Silently register Surfboard with any AI tools already installed on this machine."""
    try:
        ensure_playwright_browser()
    except Exception as exc:
        print(f"Playwright browser setup skipped: {exc}")

    paths = _config_paths()
    command, args = _server_command()
    installed = []
    for tool, path in paths.items():
        if path.parent.exists():
            try:
                _install(tool, path)
                installed.append(tool)
            except Exception:
                pass
    if installed:
        print(f"Surfboard MCP registered for: {', '.join(installed)}")
        print("Restart your AI tool(s) to activate Surfboard.")


def main() -> None:
    print("\n=== Surfboard MCP Setup ===\n")
    print("Select tools to configure (comma-separated numbers, or 'all'):\n")
    for k, v in TOOLS.items():
        print(f"  {k}) {v}")
    print()

    choice = input("Your choice: ").strip().lower()

    if choice == "all":
        selected = list(TOOLS.values())
    else:
        selected = [TOOLS[c.strip()] for c in choice.split(",") if c.strip() in TOOLS]

    if not selected:
        print("Nothing selected.")
        return

    paths = _config_paths()
    failed = []
    print()
    try:
        ensure_playwright_browser()
        print("Playwright Chromium installed.")
    except Exception as e:
        print(f"  WARNING: {e}")

    for tool in selected:
        print(f"Configuring {tool}...")
        try:
            _install(tool, paths[tool])
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append(tool)

    if failed:
        print(f"\nFailed to configure: {', '.join(failed)}")
    else:
        print("\nDone! Restart your AI tool to load Surfboard.")


if __name__ == "__main__":
    main()

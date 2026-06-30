from __future__ import annotations

import inspect
import json
import sys
from typing import Any, Optional

from integrations.api import SurfboardAPI


# ---------------------------------------------------------------------------
# Tool schema definitions (data-driven, one place to edit)
# ---------------------------------------------------------------------------

_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "browse",
        "description": "Navigate to a URL and get the page content as structured text. Returns a tab_id — pass it to expand/click/fill to work on that specific tab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to"},
                "tab_id": {"type": "integer", "description": "Tab to reuse (omit to open a new tab)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click an element on the current page by its ID number",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "integer", "description": "The element ID to click"},
                "tab_id": {"type": "integer", "description": "Tab to operate on (from browse result)"},
                "minimal": {"type": "boolean", "description": "Skip returning the full page (default: true)"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "fill",
        "description": "Type text into an input field by its ID number",
        "inputSchema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer", "description": "The input element ID"},
                "text": {"type": "string", "description": "The text to type"},
                "tab_id": {"type": "integer", "description": "Tab to operate on (from browse result)"},
            },
            "required": ["element_id", "text"],
        },
    },
    {
        "name": "fill_and_submit",
        "description": "Type text into an input and press Enter",
        "inputSchema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer"},
                "text": {"type": "string"},
                "tab_id": {"type": "integer"},
            },
            "required": ["element_id", "text"],
        },
    },
    {
        "name": "search",
        "description": "Search the web for a query",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "get_page",
        "description": "Get the current page content",
        "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}},
    },
    {
        "name": "get_full_text",
        "description": "Extract the full rendered text content of the current page (not just structured sections)",
        "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}},
    },
    {
        "name": "get_section",
        "description": "Get the full untruncated content of a specific section by its ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "integer", "description": "The section ID"},
                "tab_id": {"type": "integer"},
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "get_console_logs",
        "description": "Get accumulated browser console logs (useful for debugging JS errors)",
        "inputSchema": {
            "type": "object",
            "properties": {"tab_id": {"type": "integer", "description": "Tab to get logs from (omit for active tab)"}},
        },
    },
    {
        "name": "expand",
        "description": "Expand a collapsed section by its ID to reveal its content or subsections",
        "inputSchema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "integer", "description": "The section ID to expand"},
                "tab_id": {"type": "integer"},
                "minimal": {"type": "boolean", "description": "Skip returning the full page (default: true)"},
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "collapse",
        "description": "Collapse an expanded section by its ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "integer", "description": "The section ID to collapse"},
                "tab_id": {"type": "integer"},
                "minimal": {"type": "boolean", "description": "Skip returning the full page (default: true)"},
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "back", "description": "Go back to the previous page",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "forward", "description": "Go forward to the next page",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tab_new", "description": "Create a new tab",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tab_switch", "description": "Switch to a tab by ID",
        "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}, "required": ["tab_id"]},
    },
    {
        "name": "tab_close", "description": "Close the active tab (cannot close the last remaining tab)",
        "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}},
    },
    {
        "name": "refresh",
        "description": "Refresh the current page (optionally specify a tab_id)",
        "inputSchema": {
            "type": "object",
            "properties": {"tab_id": {"type": "integer", "description": "Tab to refresh (omit for active tab)"}},
        },
    },
    {
        "name": "status",
        "description": "Get browser status (tabs, current URL, navigation state)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "evaluate",
        "description": "Execute JavaScript on the current page and return the result",
        "inputSchema": {
            "type": "object",
            "properties": {
                "js_code": {"type": "string", "description": "JavaScript code to execute"},
                "tab_id": {"type": "integer"},
            },
            "required": ["js_code"],
        },
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the current page (returns base64 PNG)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional file path to save screenshot"},
                "tab_id": {"type": "integer"},
            },
        },
    },
    {
        "name": "wait_for_load",
        "description": "Wait for the current page to reach network idle before continuing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout_ms": {"type": "integer", "description": "Maximum wait time in milliseconds"},
                "tab_id": {"type": "integer"},
            },
        },
    },
    {
        "name": "wait_for_element",
        "description": "Wait for a CSS selector to appear on the page (for SPAs/dynamic content)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector to wait for"},
                "timeout_ms": {"type": "integer", "description": "Maximum wait time in milliseconds (default 10000)"},
                "tab_id": {"type": "integer"},
            },
            "required": ["selector"],
        },
    },
    {
        "name": "scroll_to", "description": "Scroll an element into view by its element ID",
        "inputSchema": {
            "type": "object",
            "properties": {"element_id": {"type": "integer"}, "tab_id": {"type": "integer"}},
            "required": ["element_id"],
        },
    },
    {
        "name": "scroll_by", "description": "Scroll the viewport by a pixel offset",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "tab_id": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "hover", "description": "Hover over an element by its element ID",
        "inputSchema": {
            "type": "object",
            "properties": {"element_id": {"type": "integer"}, "tab_id": {"type": "integer"}},
            "required": ["element_id"],
        },
    },
    {
        "name": "press_key",
        "description": "Press a keyboard key (e.g. 'Enter', 'Escape', 'Tab', 'ArrowDown') on the current page",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key to press"},
                "tab_id": {"type": "integer"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "clipboard_copy", "description": "Copy text to the system clipboard via the browser page",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to copy"},
                "tab_id": {"type": "integer"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "clipboard_read", "description": "Read text from the system clipboard via the browser page",
        "inputSchema": {"type": "object", "properties": {"tab_id": {"type": "integer"}}},
    },
    {
        "name": "highlight",
        "description": "Highlight elements on the page by their element IDs (yellow outline + background). Returns per-ID status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "eids": {"type": "array", "items": {"type": "integer"}, "description": "Element IDs to highlight (empty array clears highlights)"},
                "tab_id": {"type": "integer"},
            },
            "required": ["eids"],
        },
    },
    {
        "name": "clear_cookies", "description": "Clear all browser cookies, including persisted session cookies",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# Tool name → API method mapping (for _call_tool dispatch)
# NOTE: param spec keys MUST match the API method parameter names exactly.
_TOOL_DISPATCH: dict[str, tuple[str, dict[str, Any]]] = {
    "browse": ("_navigate", {"url": "", "tab_id": None, "push_history": True}),
    "click": ("_click", {"target": "", "tab_id": None, "minimal": True}),
    "fill": ("_fill", {"element_id": 0, "text": "", "tab_id": None}),
    "fill_and_submit": ("_fill_and_submit", {"element_id": 0, "text": "", "tab_id": None}),
    "search": ("_search", {"query": ""}),
    "get_page": ("_get_page", {"tab_id": None}),
    "get_full_text": ("_get_full_text", {"tab_id": None}),
    "get_section": ("_get_section", {"section_id": 0, "tab_id": None}),
    "get_console_logs": ("get_console_logs", {"tab_id": None}),
    "expand": ("_expand", {"section_id": 0, "tab_id": None, "minimal": True}),
    "collapse": ("_collapse", {"section_id": 0, "tab_id": None, "minimal": True}),
    "back": ("_back", {}),
    "forward": ("_forward", {}),
    "tab_new": ("_tab_new", {}),
    "tab_switch": ("_tab_switch", {"tab_id": 0}),
    "tab_close": ("_tab_close", {"tab_id": None}),
    "refresh": ("_refresh", {"tab_id": None}),
    "status": ("_status", {}),
    "evaluate": ("_evaluate", {"js_code": "", "tab_id": None}),
    "screenshot": ("_screenshot", {"path": None, "tab_id": None}),
    "wait_for_load": ("_wait_for_load", {"timeout_ms": 10000, "tab_id": None}),
    "wait_for_element": ("_wait_for_element", {"selector": "", "timeout_ms": 10000, "tab_id": None}),
    "scroll_to": ("_scroll_to", {"element_id": 0, "tab_id": None}),
    "scroll_by": ("_scroll_by", {"x": 0, "y": 0, "tab_id": None}),
    "hover": ("_hover", {"element_id": 0, "tab_id": None}),
    "press_key": ("_press_key", {"key": "", "tab_id": None}),
    "clipboard_copy": ("_clipboard_copy", {"text": "", "tab_id": None}),
    "clipboard_read": ("_clipboard_read", {"tab_id": None}),
    "highlight": ("_highlight", {"eids": [], "tab_id": None}),
    "clear_cookies": ("_clear_cookies", {}),
}

class SurfboardMCPServer:
    def __init__(self) -> None:
        self.api = SurfboardAPI()

    def handle_request(self, request: dict[str, Any]) -> Optional[dict[str, Any]]:
        method = request.get("method", "")
        rid = request.get("id")

        if rid is None:
            return None

        if method == "initialize":
            return self._initialize(request)
        elif method in ("tools/list", "list_tools"):
            return self._list_tools(request)
        elif method in ("tools/call", "call_tool"):
            return self._call_tool(request)
        elif method == "ping":
            return {"jsonrpc": "2.0", "id": rid, "result": {}}
        else:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

    def _initialize(self, request: dict) -> dict:
        client_version = request.get("params", {}).get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": client_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "surfboard", "version": "0.1.0"},
            },
        }

    def _list_tools(self, request: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"tools": _TOOL_DEFS},
        }

    def _call_tool(self, request: dict) -> dict:
        params = request.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})
        req_id = request.get("id")

        entry = _TOOL_DISPATCH.get(name)
        if entry is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown tool: {name}"},
            }

        method_name, param_spec = entry
        kwargs = {}
        for key, default in param_spec.items():
            raw = args.get(key)
            kwargs[key] = raw if raw is not None else default

        method = getattr(self.api, method_name)
        sig = inspect.signature(method)
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        result = method(**filtered)

        if "error" in result:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": result["error"]},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": self._result_to_content(result)},
        }

    def _result_to_content(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        if "screenshot_base64" in result:
            return [
                {"type": "text", "text": "Screenshot captured"},
                {"type": "image", "data": result["screenshot_base64"], "mimeType": "image/png"},
            ]
        return [{"type": "text", "text": json.dumps(result, indent=None, separators=(",", ":"))}]

    def run(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                if response is not None:
                    print(json.dumps(response), flush=True)
            except json.JSONDecodeError as e:
                print(json.dumps({"jsonrpc": "2.0", "error": {"code": -32700, "message": f"Parse error: {e}"}}), flush=True)
            except Exception as e:
                print(json.dumps({"jsonrpc": "2.0", "error": {"code": -32603, "message": f"Internal error: {e}"}}), flush=True)


def main() -> None:
    server = SurfboardMCPServer()
    server.run()


if __name__ == "__main__":
    main()

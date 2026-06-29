from __future__ import annotations

import json
import sys
from typing import Any, Optional

from integrations.api import SurfboardAPI


class SurfboardMCPServer:
    def __init__(self) -> None:
        self.api = SurfboardAPI()

    def handle_request(self, request: dict[str, Any]) -> Optional[dict[str, Any]]:
        method = request.get("method", "")
        rid = request.get("id")

        # Notifications (no id) should not receive a response
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
        tools = [
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
                        "id": {"type": "integer", "description": "The element ID to click"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on (from browse result)"},
                        "minimal": {"type": "boolean", "description": "Skip fetching the updated page (default: false)"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "fill",
                "description": "Type text into an input field by its ID number",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The input element ID"},
                        "text": {"type": "string", "description": "The text to type"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on (from browse result)"},
                    },
                    "required": ["id", "text"],
                },
            },
            {
                "name": "search",
                "description": "Search the web for a query",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"}
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_page",
                "description": "Get the current page content",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tab_id": {"type": "integer", "description": "Tab to get (omit for active tab)"},
                    },
                },
            },
            {
                "name": "expand",
                "description": "Expand a collapsed section by its ID to reveal its content or subsections",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The section ID to expand"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on (from browse result)"},
                        "minimal": {"type": "boolean", "description": "Skip returning the full page (default: false)"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "collapse",
                "description": "Collapse an expanded section by its ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The section ID to collapse"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on (from browse result)"},
                        "minimal": {"type": "boolean", "description": "Skip returning the full page (default: false)"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "back",
                "description": "Go back to the previous page",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "forward",
                "description": "Go forward to the next page",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "tab_new",
                "description": "Create a new tab",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "tab_switch",
                "description": "Switch to a tab by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "Tab ID to switch to"}
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "refresh",
                "description": "Refresh the current page",
                "inputSchema": {"type": "object", "properties": {}},
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
                        "js": {"type": "string", "description": "JavaScript code to execute"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["js"],
                },
            },
            {
                "name": "get_full_text",
                "description": "Extract the full rendered text content of the current page (not just structured sections)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                },
            },
            {
                "name": "screenshot",
                "description": "Take a screenshot of the current page (returns base64 PNG)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Optional file path to save screenshot"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                },
            },
            {
                "name": "fill_and_submit",
                "description": "Type text into an input field by its ID number and press Enter to submit",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The input element ID"},
                        "text": {"type": "string", "description": "The text to type"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on (from browse result)"},
                    },
                    "required": ["id", "text"],
                },
            },
            {
                "name": "wait_for_load",
                "description": "Wait for the current page to reach network idle before continuing",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "timeout_ms": {"type": "integer", "description": "Maximum wait time in milliseconds"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                },
            },
            {
                "name": "scroll_to",
                "description": "Scroll an element into view by its element ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The element ID to scroll into view"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "scroll_by",
                "description": "Scroll the viewport by a pixel offset",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "Horizontal scroll offset"},
                        "y": {"type": "integer", "description": "Vertical scroll offset"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["x", "y"],
                },
            },
            {
                "name": "hover",
                "description": "Hover over an element by its element ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The element ID to hover"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "press_key",
                "description": "Press a keyboard key (e.g. 'Enter', 'Escape', 'Tab', 'ArrowDown') on the current page",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Key to press"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["key"],
                },
            },
            {
                "name": "clipboard_copy",
                "description": "Copy text to the system clipboard via the browser page",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to copy"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "clipboard_read",
                "description": "Read text from the system clipboard via the browser page",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                },
            },
            {
                "name": "highlight",
                "description": "Highlight elements on the page by their element IDs (yellow outline + background). Returns per-ID status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ids": {"type": "array", "items": {"type": "integer"}, "description": "Element IDs to highlight (empty array clears highlights)"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["ids"],
                },
            },
            {
                "name": "tab_close",
                "description": "Close the active tab (cannot close the last remaining tab)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tab_id": {"type": "integer", "description": "Tab ID to close (omit for active tab)"},
                    },
                },
            },
            {
                "name": "get_section",
                "description": "Get the full untruncated content of a specific section by its ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The section ID"},
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["id"],
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
                        "tab_id": {"type": "integer", "description": "Tab to operate on"},
                    },
                    "required": ["selector"],
                },
            },
        ]

        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"tools": tools},
        }

    def _call_tool(self, request: dict) -> dict:
        params = request.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})

        req_id = request.get("id")

        if name == "browse":
            url = args.get("url", "")
            result = self.api._navigate(url, tab_id=args.get("tab_id"))
        elif name == "click":
            eid = args.get("id", 0)
            result = self.api._click(str(eid), tab_id=args.get("tab_id"), minimal=args.get("minimal", False))
        elif name == "fill":
            result = self.api._fill(args.get("id", 0), args.get("text", ""), tab_id=args.get("tab_id"))
        elif name == "search":
            query = args.get("query", "")
            result = self.api._search(query)
        elif name == "get_page":
            result = self.api._get_page(tab_id=args.get("tab_id"))
        elif name == "expand":
            result = self.api._expand(args.get("id", 0), tab_id=args.get("tab_id"), minimal=args.get("minimal", False))
        elif name == "collapse":
            result = self.api._collapse(args.get("id", 0), tab_id=args.get("tab_id"), minimal=args.get("minimal", False))
        elif name == "back":
            result = self.api._back()
        elif name == "forward":
            result = self.api._forward()
        elif name == "tab_new":
            result = self.api._tab_new()
        elif name == "tab_switch":
            result = self.api._tab_switch(args.get("id", 0))
        elif name == "tab_close":
            result = self.api._tab_close()
        elif name == "refresh":
            result = self.api._refresh()
        elif name == "status":
            result = self.api._status()
        elif name == "evaluate":
            result = self.api._evaluate(args.get("js", ""), tab_id=args.get("tab_id"))
        elif name == "get_full_text":
            result = self.api._get_full_text(tab_id=args.get("tab_id"))
        elif name == "screenshot":
            result = self.api._screenshot(path=args.get("path"), tab_id=args.get("tab_id"))
        elif name == "fill_and_submit":
            result = self.api._fill_and_submit(args.get("id", 0), args.get("text", ""), tab_id=args.get("tab_id"))
        elif name == "wait_for_load":
            result = self.api._wait_for_load(args.get("timeout_ms", 10000), tab_id=args.get("tab_id"))
        elif name == "wait_for_element":
            result = self.api._wait_for_element(args.get("selector", ""), args.get("timeout_ms", 10000), tab_id=args.get("tab_id"))
        elif name == "scroll_to":
            result = self.api._scroll_to(args.get("id", 0), tab_id=args.get("tab_id"))
        elif name == "scroll_by":
            result = self.api._scroll_by(args.get("x", 0), args.get("y", 0), tab_id=args.get("tab_id"))
        elif name == "hover":
            result = self.api._hover(args.get("id", 0), tab_id=args.get("tab_id"))
        elif name == "press_key":
            result = self.api._press_key(args.get("key", ""), tab_id=args.get("tab_id"))
        elif name == "clipboard_copy":
            result = self.api._clipboard_copy(args.get("text", ""), tab_id=args.get("tab_id"))
        elif name == "clipboard_read":
            result = self.api._clipboard_read(tab_id=args.get("tab_id"))
        elif name == "highlight":
            result = self.api._highlight(args.get("ids", []), tab_id=args.get("tab_id"))
        elif name == "get_section":
            result = self.api._get_section(args.get("id", 0), tab_id=args.get("tab_id"))
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown tool: {name}"},
            }

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
        return [{"type": "text", "text": json.dumps(result, indent=2)}]

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

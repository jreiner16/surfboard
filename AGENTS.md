# Surfboard - Web browser tool for AI agents

Surfboard uses **Playwright** (headless Chromium) for real JS rendering — no CAPTCHA walls, no empty JS walls.

## MCP tools (via surfboard server)

When you need to browse the web, search, or fetch live content, use the `surfboard` MCP tools. Available tools:

- `surfboard_search` — Search the web via Google. Pass `query` string. Opens a new tab by default; pass `tab_id` to reuse an existing tab.
- `surfboard_browse` — Navigate to a URL. Pass `url` string.
- `surfboard_click` — Click an element by its ID number. Pass `target` integer. Navigates on links, triggers actions on buttons. Default `minimal=true` (omit page structure from response).
- `surfboard_get_page` — Get the current page content (sections, elements, links).
- `surfboard_back` / `surfboard_forward` — Navigate history.
- `surfboard_tab_new` / `surfboard_tab_switch` — Tab management. Pass `tab_id` integer.
- `surfboard_refresh` — Reload current page.
- `surfboard_status` — Browser status (tabs, URL, navigation).
- `surfboard_evaluate` — Execute JavaScript on the page. Pass `js_code` string.
- `surfboard_get_full_text` — Extract the full rendered text (document.body.innerText).
- `surfboard_screenshot` — Take a full-page PNG screenshot (base64).
- `surfboard_fill` — Type text into an input field. Pass `element_id`, `text`.
- `surfboard_fill_and_submit` — Type text into an input and press Enter. Pass `element_id`, `text`.
- `surfboard_press_key` — Press a keyboard key (e.g., 'Enter', 'Escape').
- `surfboard_clipboard_copy` / `surfboard_clipboard_read` — Browser clipboard access.
- `surfboard_highlight` — Highlight elements by their IDs (yellow outline). Pass `eids` array.
- `surfboard_scroll_by` / `surfboard_scroll_to` — Scroll the viewport or an element into view.
- `surfboard_hover` — Hover over an element by its ID.

### Workflow
1. `surfboard_search` to find something
2. `surfboard_click <target>` to open a result
3. `surfboard_get_page` to read the content
4. Use `surfboard_get_full_text` if the page has JS-rendered content not showing in sections
5. Use `surfboard_evaluate` with `js_code` to run custom JS and inspect state
6. Repeat as needed

## CLI commands

| Command | Description |
|---------|-------------|
| `surfboard setup` | Interactive setup wizard |
| `surfboard status` | Show Surfboard status |
| `surfboard log` | Show browsing history |
| `surfboard log --tail` | Tail history in real-time |
| `surfboard log -n 10` | Show last 10 entries |
| `surfboard help` | Show available commands |
| `surfboard-mcp` | Start MCP server (stdin/stdout) |
| `surfboard-install` | Interactive setup wizard (standalone) |
| `surfboard-post-install` | Silent auto-registration |

### Setup
```bash
pip install -e .
playwright install chromium
surfboard setup
```

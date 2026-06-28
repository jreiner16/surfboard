# Surfboard 🌊

**The Web Browser for LLMs**

*Most LLM "search" tools are really just glorified web scrapers.*
<br>Surfboard lets LLMs click links, scroll, fill forms, switch tabs, and navigate websites -- all through a token-efficient MCP server.
<br>Surfboard uses Playwright (headless Chromium) to render JS-heavy pages -- sidestepping many bot walls, empty JS shells, and client-side rendering.
<br>By structuring results as tree-like JSONs, Surfboard both prevents token overflows on large sites and also allows the LLM to navigate intentionally and efficiently.

## Install

```bash
pip install -e .
```

If your AI tool supports auto discovery (e.g. Claude Desktop, Cursor, OpenCode, VS Code Copilot, Windsurf, Claude Code CLI), run:

```bash
surfboard setup
```

This registers Surfboard as an MCP server in your tool's config. After restarting the tool, the LLMs should be able to browse and interact with the web more thoroughly using Surfboard.

## CLI commands

| Command | Description |
|---------|-------------|
| `surfboard setup` | Interactive setup wizard |
| `surfboard status` | Show tool config status + history stats |
| `surfboard log` | Show browsing history |
| `surfboard log --tail` | Tail history in real-time |
| `surfboard log -n 10` | Show last 10 entries |
| `surfboard help` | Show available commands |
| `surfboard-mcp` | Start MCP server (stdin/stdout) |
| `surfboard-install` | Standalone setup wizard |
| `surfboard-post-install` | Silent auto-registration |


### Typical workflow

1. **Search** — `surfboard_search("query")` runs a Google search
2. **Navigate** — `surfboard_browse(url)` opens a page, returns structured sections + interactive elements
3. **Read** — `surfboard_get_page` returns the page structure with sections, links, buttons, inputs
4. **Dig deeper** — `surfboard_get_full_text` grabs `document.body.innerText` for JS-rendered content; `surfboard_evaluate("JS code")` runs arbitrary JavaScript
5. **Interact** — `surfboard_click(id)`, `surfboard_fill(id, text)`, `surfboard_fill_and_submit(id, text)`, `surfboard_hover(id)`, `surfboard_scroll_to(id)`, `surfboard_scroll_by(x, y)`, `surfboard_wait_for_load(timeout_ms)`, `surfboard_press_key(key)`

### MCP tools

`surfboard_search` `surfboard_browse` `surfboard_click` `surfboard_fill` `surfboard_hover` `surfboard_scroll_to` `surfboard_scroll_by` `surfboard_wait_for_load` `surfboard_get_page` `surfboard_back` `surfboard_forward` `surfboard_tab_new` `surfboard_tab_switch` `surfboard_refresh` `surfboard_status` `surfboard_evaluate` `surfboard_get_full_text` `surfboard_screenshot` `surfboard_fill_and_submit` `surfboard_press_key` `surfboard_clipboard_copy` `surfboard_clipboard_read` `surfboard_highlight`

### Disclaimer
Surfboard is designed for interaction, not bulk extraction. If an LLM only needs a one-shot context dump from a webpage, a traditional scraper is usually faster. **When it needs to navigate, click, search within a site, or interact with dynamic content, Surfboard is superior.**

### Tricks & anti-blocking

- Reddit URLs auto-rewrite to the JSON API (no CAPTCHA)
- Twitter/X URLs auto-rewrite to Nitter (no JS wall)
- Medium URLs auto-rewrite to Scribe (no paywall)
- AMP URLs auto-strip the `/amp` suffix
- DuckDuckGo/Google redirect links are unwrapped to real URLs
- Bot-block patterns (Cloudflare, CAPTCHA, etc.) are detected and reported

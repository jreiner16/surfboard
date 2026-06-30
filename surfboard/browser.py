from __future__ import annotations

import json
import os
from pathlib import Path

from surfboard.fetcher import FetchResult, _is_bot_block

PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

_STEALTH_INIT_SCRIPT = """
// Remove webdriver property
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Chrome plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Chrome runtime
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {},
};

// Permissions
navigator.permissions.query = (() => {
    const original = navigator.permissions.query.bind(navigator.permissions);
    return (params) => {
        if (params.name === 'notifications') {
            return Promise.resolve({ state: 'denied', onchange: null });
        }
        return original(params);
    };
})();

// WebGL vendor
const getExt = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, ...args) {
    const ctx = getExt.call(this, type, ...args);
    if (ctx && type === 'webgl') {
        const getParam = ctx.getParameter;
        ctx.getParameter = function(param) {
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return getParam.call(this, param);
        };
    }
    return ctx;
};

// Remove headless chrome detection
Object.defineProperty(navigator, 'connection', {
    get: () => ({ rtt: 100, effectiveType: '4g' }),
});

// Fake device memory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
});

// Fake hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
});
"""


class BrowserFetcher:
    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._console_logs: list[str] = []

    def _start(self):
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-component-update",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=PLAYWRIGHT_UA,
            viewport={"width": 1280, "height": 800},
            device_scale_factor=1,
            locale="en-US",
            timezone_id="America/New_York",
        )
        self._page = self._context.new_page()
        self._page.add_init_script(_STEALTH_INIT_SCRIPT)

        # Capture console logs
        self._console_logs = []
        self._page.on("console", lambda msg: self._console_logs.append(f"[{msg.type}] {msg.text}"))

        self._ensure_clipboard_permissions()
        self._restore_cookies()

    def get_console_logs(self) -> list[str]:
        logs = list(self._console_logs)
        self._console_logs = []
        return logs

    def peek_console_logs(self) -> list[str]:
        return list(self._console_logs)

    def _cookie_path(self) -> Path:
        return Path.home() / ".surfboard" / "cookies.json"

    def _save_cookies(self):
        cookies = self._context.cookies()
        path = self._cookie_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cookies, indent=2))

    def _restore_cookies(self):
        path = self._cookie_path()
        if path.exists():
            cookies = json.loads(path.read_text())
            if cookies:
                self._context.add_cookies(cookies)

    def fetch(self, url: str) -> FetchResult:
        if not self._page:
            try:
                self._start()
            except ImportError:
                return FetchResult(
                    url=url, html="", status_code=0, headers={}, final_url=url,
                    error="playwright not installed. Run: pip install playwright && playwright install chromium",
                )
            except Exception as e:
                return FetchResult(
                    url=url, html="", status_code=0, headers={}, final_url=url,
                    error=f"Playwright init failed: {e}",
                )

        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
            self._page.wait_for_timeout(1500)

            if _is_bot_block(self._page.content(), 200):
                return FetchResult(
                    url=url, html="", status_code=200, headers={}, final_url=self._page.url,
                    error=f"Bot/CAPTCHA wall detected at {self._page.url}",
                )

            html = self._page.content()
            self._save_cookies()
            return FetchResult(
                url=url, html=html, status_code=200, headers={}, final_url=self._page.url,
            )
        except Exception as e:
            return FetchResult(
                url=url, html="", status_code=0, headers={}, final_url=url,
                error=str(e),
            )

    def evaluate(self, js_code: str) -> str:
        if not self._page:
            return "error: no page loaded"
        try:
            result = self._page.evaluate(js_code)
            logs = self.get_console_logs()
            output = str(result) if result is not None else "null"
            if logs:
                output += "\n[console]\n" + "\n".join(logs)
            return output
        except Exception as e:
            logs = self.get_console_logs()
            msg = f"error: {e}"
            if logs:
                msg += "\n[console]\n" + "\n".join(logs)
            return msg

    def get_full_text(self) -> str:
        if not self._page:
            return ""
        try:
            return self._page.evaluate("document.body.innerText")
        except Exception:
            return ""

    def screenshot(self, path: str | None = None) -> bytes | None:
        if not self._page:
            return None
        try:
            opts = {"type": "png", "full_page": True}
            if path:
                opts["path"] = path
            return self._page.screenshot(**opts)
        except Exception:
            return None

    def content(self) -> str:
        if not self._page:
            return ""
        try:
            return self._page.content()
        except Exception:
            return ""

    def current_url(self) -> str:
        if not self._page:
            return ""
        try:
            return self._page.url
        except Exception:
            return ""

    def wait_for_load(self, timeout_ms: int = 10000) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return {"loaded": True, "timeout_ms": timeout_ms}
        except Exception as e:
            return {"error": str(e)}

    def _scroll_into_view(self, selector: str) -> None:
        try:
            self._page.evaluate(f"""() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (el) el.scrollIntoView({{block: 'center', behavior: 'instant'}});
            }}""")
            self._page.wait_for_timeout(200)
        except Exception:
            pass

    def click(self, selector: str, fallback_selectors: list[str] | None = None) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        selectors_to_try = [selector]
        if fallback_selectors:
            selectors_to_try.extend(fallback_selectors)

        last_error = None
        for sel in selectors_to_try:
            try:
                el = self._page.query_selector(sel)
                if el:
                    self._scroll_into_view(sel)
                    self._page.click(sel)
                    return {"clicked": sel, "selector_used": sel}
            except Exception as e:
                last_error = str(e)
                continue

        return {"error": f"click failed for all selectors: {last_error}"}

    def hover(self, selector: str) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.hover(selector)
            return {"hovered": selector}
        except Exception as e:
            return {"error": str(e)}

    def scroll_to(self, selector: str) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            result = self._page.evaluate(f"""() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return null;
                el.scrollIntoView({{block: 'center', behavior: 'smooth'}});
                return true;
            }}""")
            if result is None:
                return {"error": f"Element not found: {selector}"}
            return {"scrolled_to": selector}
        except Exception as e:
            return {"error": str(e)}

    def scroll_by(self, x: int, y: int) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.evaluate(f"window.scrollBy({x}, {y})")
            return {"scrolled_by": [x, y]}
        except Exception as e:
            return {"error": str(e)}

    def select_option(self, selector: str, value: str) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.select_option(selector, value)
            return {"selected": selector, "value": value}
        except Exception as e:
            return {"error": str(e)}

    def fill(self, selector: str, text: str) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._scroll_into_view(selector)
            # Playwright fill() triggers real input events (works for most frameworks)
            self._page.fill(selector, text)
            # Additionally fire synthetic input+change for frameworks that use addEventListener
            self._page.evaluate(f"""() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return;
                ['input', 'change'].forEach(type => {{
                    el.dispatchEvent(new Event(type, {{ bubbles: true }}));
                }});
            }}""")
            return {"filled": selector, "value": text}
        except Exception as e:
            return {"error": str(e)}

    def press_key(self, key: str) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            # Support key combos: "Ctrl+C", "Shift+Enter", "Ctrl+Shift+F", etc.
            if "+" in key:
                parts = key.split("+")
                # All but the last are modifiers, the last is the actual key
                modifiers = parts[:-1]
                actual_key = parts[-1]
                # Map common modifier names
                mod_map = {"ctrl": "Control", "shift": "Shift", "alt": "Alt", "meta": "Meta"}
                for mod in modifiers:
                    mapped = mod_map.get(mod.lower(), mod)
                    self._page.keyboard.down(mapped)
                self._page.keyboard.press(actual_key)
                for mod in modifiers:
                    mapped = mod_map.get(mod.lower(), mod)
                    self._page.keyboard.up(mapped)
            else:
                self._page.keyboard.press(key)
            return {"pressed": key}
        except Exception as e:
            return {"error": str(e)}

    def clipboard_copy(self, text: str) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.evaluate(f"""() => {{
                const ta = document.createElement('textarea');
                ta.value = {json.dumps(text)};
                ta.style.position = 'fixed';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                try {{
                    document.execCommand('copy');
                    ta.remove();
                    return true;
                }} catch(e) {{
                    ta.remove();
                    throw e;
                }}
            }}""")
            return {"copied": text, "length": len(text)}
        except Exception as e:
            return {"error": str(e)}

    def clipboard_read(self) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            text = self._page.evaluate("navigator.clipboard.readText()")
            return {"text": text}
        except Exception as e:
            return {"error": str(e)}

    def _ensure_clipboard_permissions(self):
        if self._context:
            try:
                self._context.grant_permissions(["clipboard-read", "clipboard-write"])
            except Exception:
                pass

    def highlight_elements(self, eids: list[int]) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            result = self._page.evaluate(f"""() => {{
                const requested = {json.dumps(eids)};
                const totalElements = document.querySelectorAll('a, button, input, textarea, select, [tabindex]').length;

                document.querySelectorAll('.surfboard-highlight').forEach(el => {{
                    el.style.outline = el.dataset.surfboardOrigOutline || '';
                    el.style.backgroundColor = el.dataset.surfboardOrigBg || '';
                    el.classList.remove('surfboard-highlight');
                }});

                if (requested.length === 0) return {{ status: 'cleared', total_elements: totalElements }};

                const found = [];
                const notFound = [];
                let count = 0;
                document.querySelectorAll('a, button, input, textarea, select, [tabindex]').forEach((el, idx) => {{
                    const eid = idx + 1;
                    if (requested.includes(eid)) {{
                        el.dataset.surfboardOrigOutline = el.style.outline;
                        el.dataset.surfboardOrigBg = el.style.backgroundColor;
                        el.style.outline = '3px solid #FFD93D';
                        el.style.backgroundColor = 'rgba(255, 217, 61, 0.15)';
                        el.classList.add('surfboard-highlight');
                        found.push(eid);
                        count++;
                    }}
                }});

                requested.forEach(id => {{
                    if (!found.includes(id)) notFound.push(id);
                }});

                return {{
                    status: 'highlighted ' + count + ' of ' + requested.length + ' elements',
                    found: found,
                    not_found: notFound,
                    total_elements: totalElements
                }};
            }}""")
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    def wait_for_element(self, selector: str, timeout_ms: int = 10000) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.wait_for_selector(selector, timeout=timeout_ms)
            return {"found": True, "selector": selector, "timeout_ms": timeout_ms}
        except Exception as e:
            return {"error": str(e)}

    def submit_form(self, selector: str) -> dict:
        """Smart form submission with multiple fallback strategies."""
        if not self._page:
            return {"error": "no page loaded"}
        strategies = []

        # Strategy 1: Press Enter on the focused element
        strategies.append(("Enter key", lambda: self._page.keyboard.press("Enter")))

        # Strategy 2: Find and click any submit button in the form
        strategies.append(("submit button", lambda: self._page.evaluate(f"""() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const form = el.closest('form');
            if (!form) return false;
            const btn = form.querySelector('button[type=submit], input[type=submit], button:has(svg), button[aria-label*=search i], button:last-of-type');
            if (btn) {{ btn.click(); return true; }}
            return false;
        }}""")))

        # Strategy 3: JS form.submit()
        strategies.append(("form.submit()", lambda: self._page.evaluate(f"""() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const form = el.closest('form');
            if (form) {{ form.submit(); return true; }}
            return false;
        }}""")))

        # Strategy 4: Dispatch submit event on form
        strategies.append(("submit event", lambda: self._page.evaluate(f"""() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const form = el.closest('form');
            if (form) {{
                form.dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
                return true;
            }}
            return false;
        }}""")))

        # Strategy 5: Click any nearby button
        strategies.append(("nearby button", lambda: self._page.evaluate(f"""() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const form = el.closest('form');
            if (form) {{
                const btns = form.querySelectorAll('button');
                if (btns.length > 0) {{ btns[0].click(); return true; }}
            }}
            const parent = el.parentElement;
            if (parent) {{
                const btn = parent.querySelector('button, input[type=submit]');
                if (btn) {{ btn.click(); return true; }}
            }}
            return false;
        }}""")))

        for name, strategy in strategies:
            try:
                result = strategy()
                if result is not False and result is not None:
                    return {"submitted": True, "strategy": name}
            except Exception:
                continue

        return {"error": "all form submission strategies failed"}

    def __enter__(self) -> BrowserFetcher:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self):
        exc = None
        if self._page:
            try:
                self._page.close()
            except Exception as e:
                exc = e
        if self._context:
            try:
                self._context.close()
            except Exception as e:
                exc = e
        if self._browser:
            try:
                self._browser.close()
            except Exception as e:
                exc = e
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                exc = e
        if exc:
            raise exc

"""Playwright-based headless browser with stealth, caching, and interception."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
from pathlib import Path
import urllib.request

from surfboard.fetcher import FetchResult, _is_bot_block
from surfboard.log import get_logger
from surfboard.stealth import STEALTH_INIT_SCRIPT

_logger = get_logger()

PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

RESOURCE_BLOCK_PATTERNS = [
    "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.gif",
    "**/*.svg", "**/*.webp", "**/*.ico",
    "**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.eot",
    "**/*.mp4", "**/*.webm", "**/*.ogg",
]

KNOWN_MODIFIERS = {"ctrl", "shift", "alt", "meta", "control", "command", "option"}

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Simple token-bucket rate limiter."""

    def __init__(self, calls_per_sec: float = 10.0):
        self._min_interval = 1.0 / max(calls_per_sec, 0.1)
        self._last_call = 0.0

    def acquire(self) -> float:
        now = time.time()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
            now = time.time()
        self._last_call = now
        return wait if wait > 0 else 0.0

# ---------------------------------------------------------------------------
# Cookie storage (base64-obfuscated)
# ---------------------------------------------------------------------------

def _encode_cookies(cookies: list[dict]) -> str:
    raw = json.dumps(cookies)
    return base64.b64encode(raw.encode()).decode()

def _decode_cookies(data: str) -> list[dict]:
    try:
        raw = base64.b64decode(data.encode()).decode()
        return json.loads(raw)
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Main browser class
# ---------------------------------------------------------------------------

class BrowserFetcher:
    def __init__(self, timeout: float = 30.0, block_resources: bool = False,
                 proxy: str | None = None, calls_per_sec: float = 10.0):
        self.timeout = timeout
        self.block_resources = block_resources
        self.proxy = proxy
        self.rate_limiter = RateLimiter(calls_per_sec)
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages: dict[int, object] = {}       # tab_id → Playwright Page
        self._active_tab_id: int | None = None
        self._page: object | None = None           # cached ref to active page
        self._console_logs: list[str] = []
        self._last_cookie_hash: str | None = None
        self._resource_block_enabled = block_resources
        self._request_interceptors: list[callable] = []

    # -- Lifecycle ----------------------------------------------------------

    def _ensure_page(self) -> bool:
        """Ensure browser + context are running (pages are created per-tab)."""
        if self._context:
            return True
        try:
            self._start()
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def _start(self):
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        launch_args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-component-update",
        ]
        if self.proxy:
            launch_args.append(f"--proxy-server={self.proxy}")
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=launch_args,
        )
        self._context = self._browser.new_context(
            user_agent=PLAYWRIGHT_UA,
            viewport={"width": 1280, "height": 800},
            device_scale_factor=1,
            locale="en-US",
            timezone_id="America/New_York",
        )

    def _setup_page(self, page) -> None:
        """Configure a newly-created page (stealth, routes, listeners)."""
        page.add_init_script(STEALTH_INIT_SCRIPT)
        page.set_default_timeout(10000)
        if self._resource_block_enabled:
            page.route(
                RESOURCE_BLOCK_PATTERNS,
                lambda route: route.abort(),
            )
        page.on("console", lambda msg: self._console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("request", lambda req: self._on_request(req))

    def create_page(self, tab_id: int) -> bool:
        """Create a Playwright page for *tab_id* and set it as active."""
        if not self._ensure_page():
            return False
        try:
            page = self._context.new_page()
            self._setup_page(page)
            self._pages[tab_id] = page
            self._active_tab_id = tab_id
            self._page = page
            self._ensure_clipboard_permissions()
            self._restore_cookies()
            return True
        except Exception:
            return False

    def set_active_tab(self, tab_id: int) -> bool:
        """Switch the active Playwright page to *tab_id*'s page."""
        page = self._pages.get(tab_id)
        if page is None:
            return False
        self._active_tab_id = tab_id
        self._page = page
        return True

    def close_page(self, tab_id: int) -> None:
        """Close the Playwright page for *tab_id* and update active page."""
        page = self._pages.pop(tab_id, None)
        if page:
            try:
                page.close()
            except Exception:
                pass
        if self._active_tab_id == tab_id:
            if self._pages:
                nid = next(iter(self._pages))
                self._active_tab_id = nid
                self._page = self._pages[nid]
            else:
                self._active_tab_id = None
                self._page = None

    def _on_request(self, request) -> None:
        for fn in self._request_interceptors:
            try:
                fn(request)
            except Exception:
                _logger.warn("interceptor", "request interceptor failed", "error")

    def add_request_interceptor(self, fn: callable) -> None:
        """Register a callback receiving Playwright Request objects."""
        self._request_interceptors.append(fn)

    def _try_restart(self) -> bool:
        """Attempt to restart the browser and recreate all pages (crash recovery)."""
        tab_ids = list(self._pages.keys())
        active_id = self._active_tab_id
        self._pages.clear()
        self._active_tab_id = None
        self._page = None
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
        self._browser = None
        self._context = None
        try:
            self._start()
            for tid in tab_ids:
                page = self._context.new_page()
                self._setup_page(page)
                self._pages[tid] = page
            if active_id in self._pages:
                self._active_tab_id = active_id
                self._page = self._pages[active_id]
            self._ensure_clipboard_permissions()
            self._restore_cookies()
            return True
        except Exception:
            return False

    def close(self):
        exceptions = []
        for tid in list(self._pages.keys()):
            page = self._pages.pop(tid, None)
            if page:
                try:
                    page.close()
                except Exception as e:
                    exceptions.append(e)
        self._active_tab_id = None
        self._page = None
        if self._context:
            try:
                self._context.close()
            except Exception as e:
                exceptions.append(e)
            self._context = None
        if self._browser:
            try:
                self._browser.close()
            except Exception as e:
                exceptions.append(e)
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                exceptions.append(e)
            self._playwright = None
        if exceptions:
            raise Exception(
                f"Multiple errors during browser close: {'; '.join(str(e) for e in exceptions)}"
            )

    def __enter__(self) -> BrowserFetcher:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # -- Cookie management --------------------------------------------------

    def _cookie_path(self) -> Path:
        return Path.home() / ".surfboard" / "cookies.dat"

    def _save_cookies(self):
        if not self._context:
            return
        cookies = self._context.cookies()
        cookie_hash = hashlib.sha256(json.dumps(cookies, sort_keys=True).encode()).hexdigest()
        if cookie_hash == self._last_cookie_hash:
            return
        path = self._cookie_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_encode_cookies(cookies))
        self._last_cookie_hash = cookie_hash

    def _restore_cookies(self):
        path = self._cookie_path()
        if path.exists():
            cookies = _decode_cookies(path.read_text())
            if cookies:
                self._context.add_cookies(cookies)
                self._last_cookie_hash = hashlib.sha256(
                    json.dumps(cookies, sort_keys=True).encode()
                ).hexdigest()

    def clear_cookies(self):
        if self._context:
            self._context.clear_cookies()
        path = self._cookie_path()
        if path.exists():
            path.unlink()
        self._last_cookie_hash = None

    # -- Navigation ---------------------------------------------------------

    def fetch(self, url: str) -> FetchResult:
        if not self._ensure_page():
            return FetchResult(
                url=url, html="", status_code=0, headers={}, final_url=url,
                error="playwright not installed. Run: pip install playwright && playwright install chromium",
            )
        if not self._page:
            return FetchResult(
                url=url, html="", status_code=0, headers={}, final_url=url,
                error="no page loaded",
            )
        for attempt in range(2):
            self.rate_limiter.acquire()
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))

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
                if attempt == 0 and self._try_restart():
                    _logger.warn("browse", f"Navigation failed, recovered via restart: {e}", "warn")
                    continue
                return FetchResult(
                    url=url, html="", status_code=0, headers={}, final_url=url,
                    error=str(e),
                )
        # unreachable
        return FetchResult(
            url=url, html="", status_code=0, headers={}, final_url=url,
            error="unknown fetch error",
        )

    def go_back(self) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.go_back()
            return {"navigated": True}
        except Exception as e:
            return {"error": str(e)}

    def go_forward(self) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.go_forward()
            return {"navigated": True}
        except Exception as e:
            return {"error": str(e)}

    def can_go_back(self) -> bool:
        page = self._page
        if not page:
            return False
        try:
            return bool(page.evaluate("window.navigation?.canGoBack ?? window.history.length > 1"))
        except Exception:
            return False

    def can_go_forward(self) -> bool:
        page = self._page
        if not page:
            return False
        try:
            return bool(page.evaluate("window.navigation?.canGoForward ?? false"))
        except Exception:
            return False

    def wait_for_load(self, timeout_ms: int = 10000) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.wait_for_load_state("load", timeout=timeout_ms)
            return {"loaded": True, "timeout_ms": timeout_ms}
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

    def is_pdf(self) -> bool:
        if not self._page:
            return False
        try:
            ct = self._page.evaluate("document.contentType || ''")
            return "pdf" in ct.lower()
        except Exception:
            return False

    # -- JS evaluation & extraction -----------------------------------------

    def evaluate(self, js_code: str, quiet: bool = False) -> str:
        if not self._page:
            return "error: no page loaded"
        self.rate_limiter.acquire()
        try:
            result = self._page.evaluate(js_code)
            output = str(result) if result is not None else "null"
            if not quiet:
                logs = self.get_console_logs()
                if logs:
                    output += "\n[console]\n" + "\n".join(logs)
            return output
        except Exception as e:
            msg = f"error: {e}"
            if not quiet:
                logs = self.get_console_logs()
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

    def fetch_pdf_text(self) -> str | None:
        """Extract text from a PDF loaded in the browser. Falls back to pypdf2."""
        if not self._page:
            return None
        try:
            text = self._page.evaluate("""() => {
                const el = document.querySelector('embed[type="application/pdf"], iframe[src*=".pdf"]');
                if (el) return 'PDF embed found — use fallback extractor';
                return document.body.innerText || '';
            }""")
            if text and len(text) > 20:
                return text
        except Exception:
            pass

        try:
            pdf_url = self._page.url
            from PyPDF2 import PdfReader

            req = urllib.request.Request(
                pdf_url,
                headers={"User-Agent": self._page.evaluate("navigator.userAgent")},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                pdf_bytes = resp.read()

            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            if pages:
                return "\n\n".join(pages)
        except Exception:
            pass

        return None

    # -- Console logs -------------------------------------------------------

    def get_console_logs(self) -> list[str]:
        logs = list(self._console_logs)
        self._console_logs = []
        return logs

    def peek_console_logs(self) -> list[str]:
        return list(self._console_logs)

    # -- Element interaction ------------------------------------------------

    def _scroll_into_view(self, selector: str) -> None:
        try:
            self._page.evaluate(f"""() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (el) el.scrollIntoView({{block: 'center', behavior: 'instant'}});
            }}""")
            self._page.wait_for_timeout(200)
        except Exception:
            _logger.warn("scroll", f"scrollIntoView failed for {selector}", "warn")

    def click(self, selector: str, fallback_selectors: list[str] | None = None) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        self.rate_limiter.acquire()
        selectors_to_try = [selector]
        if fallback_selectors:
            selectors_to_try.extend(fallback_selectors)

        last_error = None
        for sel in selectors_to_try:
            try:
                el = self._page.query_selector(sel)
                if el:
                    self._scroll_into_view(sel)
                    self._page.click(sel, timeout=15000)
                    return {"clicked": sel, "selector_used": sel}
            except Exception as e:
                last_error = str(e)
                continue

        return {"error": f"click failed for all selectors: {last_error}"}

    def hover(self, selector: str, fallback_selectors: list[str] | None = None) -> dict:
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
                    self._page.hover(sel, timeout=10000)
                    return {"hovered": sel, "selector_used": sel}
            except Exception as e:
                last_error = str(e)
                continue
        return {"error": f"hover failed for all selectors: {last_error}"}

    def scroll_to(self, selector: str, fallback_selectors: list[str] | None = None) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        selectors_to_try = [selector]
        if fallback_selectors:
            selectors_to_try.extend(fallback_selectors)
        for sel in selectors_to_try:
            try:
                result = self._page.evaluate(f"""() => {{
                    const el = document.querySelector({json.dumps(sel)});
                    if (!el) return null;
                    el.scrollIntoView({{block: 'center', behavior: 'instant'}});
                    return true;
                }}""")
                if result is True:
                    self._page.wait_for_timeout(200)
                    return {"scrolled_to": sel, "selector_used": sel}
            except Exception:
                continue
        return {"error": f"Element not found for any selector (tried {len(selectors_to_try)} selectors)"}

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
            self._page.fill(selector, text)
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
            if "+" in key:
                parts = key.split("+")
                modifiers = []
                actual_key = key
                for i, part in enumerate(parts):
                    if part.lower() in KNOWN_MODIFIERS:
                        modifiers.append(part)
                    else:
                        actual_key = part
                        remaining = parts[i + 1:]
                        if remaining:
                            actual_key = "+".join([part] + remaining)
                        break
                mod_map = {"ctrl": "Control", "shift": "Shift", "alt": "Alt", "meta": "Meta",
                           "control": "Control", "command": "Meta", "option": "Alt"}
                for mod in modifiers:
                    mapped = mod_map.get(mod.lower(), mod)
                    self._page.keyboard.down(mapped)
                self._page.keyboard.press(actual_key)
                for mod in reversed(modifiers):
                    mapped = mod_map.get(mod.lower(), mod)
                    self._page.keyboard.up(mapped)
            else:
                self._page.keyboard.press(key)

            normalized = key.lower().split("+")[-1]
            if normalized in ("enter", "return"):
                try:
                    self._page.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass

            return {"pressed": key}
        except Exception as e:
            return {"error": str(e)}

    def submit_form(self, selector: str) -> dict:
        """Smart form submission with multiple fallback strategies."""
        if not self._page:
            return {"error": "no page loaded"}
        strategies = []

        strategies.append(("Enter key", lambda: self._page.keyboard.press("Enter")))

        strategies.append(("submit button", lambda: self._page.evaluate(f"""() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const form = el.closest('form');
            if (!form) return false;
            const btn = form.querySelector('button[type=submit], input[type=submit], button:has(svg), button[aria-label*=search i], button:last-of-type');
            if (btn) {{ btn.click(); return true; }}
            return false;
        }}""")))
        strategies.append(("form.submit()", lambda: self._page.evaluate(f"""() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const form = el.closest('form');
            if (form) {{ form.submit(); return true; }}
            return false;
        }}""")))
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

    # -- Clipboard ----------------------------------------------------------

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

    # -- Highlighting -------------------------------------------------------

    def highlight_elements(self, eids: list[int]) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            result = self._page.evaluate(f"""() => {{
                const requested = {json.dumps(eids)};
                const SELECTOR = 'a[href], button, input:not([type=hidden]), textarea, select';
                const totalElements = document.querySelectorAll(SELECTOR).length;

                document.querySelectorAll('.surfboard-highlight').forEach(el => {{
                    el.style.outline = el.dataset.surfboardOrigOutline || '';
                    el.style.backgroundColor = el.dataset.surfboardOrigBg || '';
                    el.classList.remove('surfboard-highlight');
                }});

                if (requested.length === 0) return {{ status: 'cleared', total_elements: totalElements }};

                const found = [];
                const notFound = [];
                let count = 0;
                document.querySelectorAll(SELECTOR).forEach((el, idx) => {{
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

from __future__ import annotations

import json

from surfboard.fetcher import FetchResult, _is_bot_block

PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


class BrowserFetcher:
    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _start(self):
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
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
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)
        self._ensure_clipboard_permissions()

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
            return str(result) if result is not None else "null"
        except Exception as e:
            return f"error: {e}"

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

    def click(self, selector: str) -> dict:
        if not self._page:
            return {"error": "no page loaded"}
        try:
            self._page.click(selector)
            return {"clicked": selector}
        except Exception as e:
            return {"error": str(e)}

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

    def close(self):
        try:
            if self._page:
                self._page.close()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

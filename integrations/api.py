from __future__ import annotations

import base64
import inspect
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

from surfboard.browser import BrowserFetcher
from surfboard.cache import PageCache
from surfboard.log import get_logger
from surfboard.models import ElementType, Section, Session
from surfboard.serializers import page_to_dict, section_to_dict
from surfboard.tree import build_page

from integrations.url_rewrite import reddit_json_to_html, rewrite_url

_PDF_EXT_RE = re.compile(r"\.pdf(?:\?|#|$)", re.IGNORECASE)

_logger = get_logger()


def _css_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _ok(data: dict[str, Any] | None = None, **kw) -> dict[str, Any]:
    """Standardized success response."""
    if data is None:
        data = {}
    data.update(kw)
    return data


def _err(msg: str, **kw) -> dict[str, Any]:
    """Standardized error response."""
    return {"error": msg, **kw}


# Single source of truth for command dispatch
COMMAND_DISPATCH: dict[str, tuple[str, dict[str, Any]]] = {
    "browse": ("_navigate", {"url": "", "tab_id": None}),
    "click": ("_click", {"target": "", "tab_id": None, "minimal": True}),
    "search": ("_search", {"query": "", "tab_id": None}),
    "fill": ("_fill", {"element_id": 0, "text": "", "tab_id": None}),
    "fill_and_submit": ("_fill_and_submit", {"element_id": 0, "text": "", "tab_id": None}),
    "hover": ("_hover", {"element_id": 0, "tab_id": None}),
    "scroll_to": ("_scroll_to", {"element_id": 0, "tab_id": None}),
    "scroll_by": ("_scroll_by", {"x": 0, "y": 0, "tab_id": None}),
    "wait_for_load": ("_wait_for_load", {"timeout_ms": 10000, "tab_id": None}),
    "wait_for_element": ("_wait_for_element", {"selector": "", "timeout_ms": 10000, "tab_id": None}),
    "back": ("_back", {}),
    "forward": ("_forward", {}),
    "tab_new": ("_tab_new", {}),
    "tab_switch": ("_tab_switch", {"tab_id": 0}),
    "tab_close": ("_tab_close", {"tab_id": None}),
    "refresh": ("_refresh", {"tab_id": None}),
    "get_page": ("_get_page", {"tab_id": None}),
    "status": ("_status", {}),
    "evaluate": ("_evaluate", {"js_code": "", "tab_id": None}),
    "get_full_text": ("_get_full_text", {"tab_id": None}),
    "screenshot": ("_screenshot", {"path": None, "tab_id": None}),
    "press_key": ("_press_key", {"key": "", "tab_id": None}),
    "clipboard_copy": ("_clipboard_copy", {"text": "", "tab_id": None}),
    "clipboard_read": ("_clipboard_read", {"tab_id": None}),
    "highlight": ("_highlight", {"eids": [], "tab_id": None}),
    "get_section": ("_get_section", {"section_id": 0, "tab_id": None}),
    "get_console_logs": ("get_console_logs", {"tab_id": None}),
    "expand": ("_expand", {"section_id": 0, "tab_id": None, "minimal": True}),
    "collapse": ("_collapse", {"section_id": 0, "tab_id": None, "minimal": True}),
    "clear_cookies": ("_clear_cookies", {}),
}


class SurfboardAPI:
    def __init__(self, block_resources: bool = False, proxy: str | None = None,
                 calls_per_sec: float = 10.0, cache_ttl: float = 300.0) -> None:
        self.fetcher = BrowserFetcher(block_resources=block_resources, proxy=proxy,
                                        calls_per_sec=calls_per_sec)
        self.session = Session()
        self._page_cache = PageCache(default_ttl=cache_ttl)
        if not self.session.restore():
            self.session.create_tab()

    _PARAM_ALIASES = {
        "id": "target",
        "navigate": "browse",
        "open": "browse",
        "page": "get_page",
    }
    _PARAM_NAME_MAP = [
        ("id", "target"),
        ("id", "element_id"),
        ("id", "section_id"),
        ("id", "tab_id"),
        ("js", "js_code"),
        ("ids", "eids"),
    ]

    def call_tool(self, name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Resolve params and dispatch to the handler method. Shared by MCP and direct-API callers."""
        args = raw_args.copy()
        for alias_from, alias_to in self._PARAM_NAME_MAP:
            if alias_from in args and alias_to not in args:
                args[alias_to] = args[alias_from]

        entry = COMMAND_DISPATCH.get(name)
        if entry is None:
            mapped = self._PARAM_ALIASES.get(name)
            if mapped:
                entry = COMMAND_DISPATCH.get(mapped)
        if entry is None:
            return _err(
                f"Unknown command: {name!r}",
                hint=("Available: browse(url), search(query), click(target), "
                      "fill(element_id, text), fill_and_submit(element_id, text), hover(element_id), "
                      "scroll_to(element_id), scroll_by(x, y), wait_for_load(timeout_ms), "
                      "get_page(), get_full_text(), evaluate(js_code), back(), forward(), "
                      "refresh(), tab_new(), tab_switch(tab_id), screenshot(), "
                      "highlight(eids), press_key(key), clipboard_copy(text), "
                      "clipboard_read()."),
            )

        method_name, param_spec = entry
        kwargs = {}
        for key, default in param_spec.items():
            raw = args.get(key)
            kwargs[key] = raw if raw is not None else default

        method = getattr(self, method_name)
        sig = inspect.signature(method)
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return method(**filtered)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = request.get("cmd", request.get("method", ""))
        params = request.get("params", request.get("arguments", {})).copy()
        return self.call_tool(cmd, params)

    # -- Tab / page helpers -------------------------------------------------

    def _resolve_tab(self, tab_id: int | None = None) -> tuple[Optional[Tab], Optional[int]]:
        """Return (tab, resolved_tab_id). Creates a tab if none exists."""
        if tab_id is not None:
            if not self.session.switch_tab(tab_id):
                pass  # fall back to current active tab (legacy alias compat)
        tab = self.session.active_tab
        if not tab:
            tab = self.session.create_tab()
        return tab, tab.id

    def _ensure_browser_page(self, tab_id: int) -> bool:
        """Ensure *tab_id* has a real Playwright page and make it active."""
        if not self.fetcher.set_active_tab(tab_id):
            return self.fetcher.create_page(tab_id)
        return True

    # -- Navigation ---------------------------------------------------------

    def _navigate(self, url: str, tab_id: int | None = None) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        url, rewrite_note = rewrite_url(url)

        tab, rid = self._resolve_tab(tab_id)
        if tab is None:
            return _err(f"No tab with ID {tab_id}" if tab_id is not None else "No active tab")

        if not self._ensure_browser_page(rid):
            return _err("Failed to create browser page")

        # Check in-memory cache
        cached = self._page_cache.get(url)
        if cached is not None:
            tab.url = url
            tab.page = cached
            _logger.info("browse", f"CACHED {url}")
            return _ok(tab_id=rid, page=page_to_dict(cached), cached=True)

        # PDF detection — URL-based
        is_pdf = bool(_PDF_EXT_RE.search(url))
        if is_pdf:
            return self._handle_pdf(url, tab, rid)

        result = self.fetcher.fetch(url)
        if result.error:
            _logger.error("browse", url, "error")
            return _err(result.error)

        # Post-navigation PDF check
        if not is_pdf and self.fetcher.is_pdf():
            return self._handle_pdf_after(result, tab, rid)

        if rewrite_note == "reddit-json":
            html = reddit_json_to_html(result.html, result.final_url)
        else:
            html = result.html

        page = build_page(html, url, result.final_url)
        self._page_cache.set(url, page)
        _logger.info("browse", result.final_url)

        tab.url = result.final_url
        tab.page = page

        return _ok(tab_id=rid, page=page_to_dict(page))

    def _handle_pdf(self, url: str, tab, tab_id: int) -> dict[str, Any]:
        result = self.fetcher.fetch(url)
        if result.error:
            _logger.error("browse", url, "error")
            return _err(result.error)
        pdf_text = self.fetcher.fetch_pdf_text()
        if pdf_text:
            html = f"<html><body><pre>{pdf_text}</pre></body></html>"
            page = build_page(html, url, result.final_url)
            page.title = result.final_url.rstrip("/").split("/")[-1]
            tab.url = result.final_url
            tab.page = page
            _logger.info("browse", f"PDF: {result.final_url}")
            return _ok(tab_id=tab_id, page=page_to_dict(page), note="PDF content extracted")
        return _err("Could not extract PDF text content")

    def _handle_pdf_after(self, result, tab, tab_id: int) -> dict[str, Any]:
        pdf_text = self.fetcher.fetch_pdf_text()
        if pdf_text:
            html = f"<html><body><pre>{pdf_text}</pre></body></html>"
            page = build_page(html, result.url, result.final_url)
            page.title = result.final_url.rstrip("/").split("/")[-1]
            tab.url = result.final_url
            tab.page = page
            _logger.info("browse", f"PDF (content-type): {result.final_url}")
            return _ok(tab_id=tab_id, page=page_to_dict(page), note="PDF content extracted via content-type")
        return _err("Could not extract PDF text content")

    # -- Selector building --------------------------------------------------

    def _build_selector(self, el) -> str:
        tag = "div"
        if el.type == ElementType.LINK:
            tag = "a"
        elif el.type == ElementType.BUTTON:
            tag = "button"
        elif el.type == ElementType.TEXT_INPUT:
            tag = "input"
        elif el.type == ElementType.TEXTAREA:
            tag = "textarea"
        elif el.type == ElementType.SELECT:
            tag = "select"
        elif el.type in (ElementType.CHECKBOX, ElementType.RADIO):
            tag = "input"

        if el.attributes.get("id"):
            return f"#{el.attributes['id']}"
        if el.name:
            return f"{tag}[name={_css_quote(el.name)}]"
        if el.placeholder:
            return f"{tag}[placeholder={_css_quote(el.placeholder)}]"
        if el.href and tag == "a":
            return f"a[href={_css_quote(el.href)}]"
        if el.text:
            return f"{tag}:has-text({_css_quote(el.text[:50])})"
        return f"{tag}:nth-of-type(1)"

    def _build_fallback_selectors(self, el) -> list[str]:
        fallbacks = []
        tag = "div"
        if el.type == ElementType.BUTTON:
            tag = "button"
        elif el.type == ElementType.TEXT_INPUT:
            tag = "input"
        elif el.type == ElementType.TEXTAREA:
            tag = "textarea"

        if el.attributes.get("aria-label"):
            fallbacks.append(f"{tag}[aria-label={_css_quote(el.attributes['aria-label'])}]")

        if el.attributes.get("title"):
            fallbacks.append(f"{tag}[title={_css_quote(el.attributes['title'])}]")

        el_class = el.attributes.get("class", "")
        if el_class:
            classes = el_class.strip().split()
            if classes:
                class_sel = "".join(f".{c}" for c in classes[:2])
                fallbacks.append(f"{tag}{class_sel}")

        if el.attributes.get("role"):
            fallbacks.append(f"{tag}[role={_css_quote(el.attributes['role'])}]")

        if el.text and el.type in (ElementType.BUTTON, ElementType.LINK):
            text = el.text.strip()[:50]
            if text:
                fallbacks.append(f"{tag}:has-text({_css_quote(text)})")

        if el.text and el.type == ElementType.BUTTON:
            text = el.text.strip()[:30]
            if text:
                fallbacks.append(f"text={text}")

        return fallbacks

    # -- Element actions ----------------------------------------------------

    def _click(self, target: str | int, tab_id: int | None = None, minimal: bool | None = None) -> dict[str, Any]:
        if minimal is None:
            minimal = True
        tab, _ = self._resolve_tab(tab_id)
        if not tab or not tab.page:
            return _err("No page loaded")

        target_str = str(target).replace("#", "")
        if target_str.isdigit():
            eid = int(target_str)
            el = tab.page.element_by_id(eid)
            if not el:
                return _err(f"No element with ID {eid}")

            selector = self._build_selector(el)
            fallbacks = self._build_fallback_selectors(el)
            click_result = self.fetcher.click(selector, fallback_selectors=fallbacks)
            if "error" in click_result:
                return _err(click_result["error"], element_id=eid,
                            hint="The page DOM may have changed. Use get_page() to refresh.")

            nav_error = None
            try:
                self.fetcher.wait_for_load(timeout_ms=10000)
            except Exception as e:
                nav_error = str(e)
                _logger.warn("click", f"Post-click navigation warning: {nav_error}", "warn")

            html = self.fetcher.content()
            url = self.fetcher.current_url() or tab.url
            if html:
                tab.url = url
                tab.page = build_page(html, tab.url, url)
            elif url != tab.url:
                tab.url = url
            result = _ok(clicked=el.id, type=el.type.value, label=el.label,
                         selector=click_result.get("selector_used", selector))
            if nav_error:
                result["navigation_warning"] = nav_error
            if not minimal and tab and tab.page:
                result["page"] = page_to_dict(tab.page)
            return result

        return _err(f"Invalid target: {target}")

    def _fill(self, element_id: int, text: str, tab_id: int | None = None) -> dict[str, Any]:
        tab, _ = self._resolve_tab(tab_id)
        if not tab or not tab.page:
            return _err("No page loaded")
        el = tab.page.element_by_id(element_id)
        if not el:
            return _err(f"No element with ID {element_id}")
        if el.type not in (ElementType.TEXT_INPUT, ElementType.TEXTAREA, ElementType.SELECT):
            return _err(f"Element {element_id} is not a text input (type: {el.type.value})")
        selector = self._build_selector(el)
        if el.type == ElementType.SELECT:
            result = self.fetcher.select_option(selector, text)
        else:
            result = self.fetcher.fill(selector, text)
        if "error" in result:
            return result
        el.value = text
        _logger.info("fill", f"[{element_id}] {el.label}")
        return _ok(filled=element_id, label=el.label, value=text, selector=selector)

    def _hover(self, element_id: int, tab_id: int | None = None) -> dict[str, Any]:
        tab, _ = self._resolve_tab(tab_id)
        if not tab or not tab.page:
            return _err("No page loaded")
        el = tab.page.element_by_id(element_id)
        if not el:
            return _err(f"No element with ID {element_id}")
        selector = self._build_selector(el)
        fallbacks = self._build_fallback_selectors(el)
        result = self.fetcher.hover(selector, fallback_selectors=fallbacks)
        if "error" in result:
            return _err(result["error"], element_id=element_id,
                        hint="The page DOM may have changed since this element was loaded. Use get_page() to refresh the element list.")
        return _ok(hovered=element_id, label=el.label, selector=result.get("selector_used", selector))

    def _scroll_to(self, element_id: int, tab_id: int | None = None) -> dict[str, Any]:
        tab, _ = self._resolve_tab(tab_id)
        if not tab or not tab.page:
            return _err("No page loaded")
        el = tab.page.element_by_id(element_id)
        if not el:
            return _err(f"No element with ID {element_id}")
        selector = self._build_selector(el)
        fallbacks = self._build_fallback_selectors(el)
        result = self.fetcher.scroll_to(selector, fallback_selectors=fallbacks)
        if "error" in result:
            return _err(result["error"], element_id=element_id,
                        hint="The page DOM may have changed since this element was loaded. Use get_page() to refresh the element list.")
        return _ok(scrolled_to=element_id, label=el.label, selector=result.get("selector_used", selector))

    def _scroll_by(self, x: int, y: int, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.scroll_by(int(x), int(y))

    def _wait_for_load(self, timeout_ms: int = 10000, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.wait_for_load(int(timeout_ms))

    def _fill_and_submit(self, element_id: int, text: str, tab_id: int | None = None) -> dict[str, Any]:
        result = self._fill(element_id, text, tab_id)
        if "error" in result:
            return result
        tab, _ = self._resolve_tab(tab_id)

        el = tab.page.element_by_id(element_id) if tab and tab.page else None
        selector = self._build_selector(el) if el else None

        submit_result = self.fetcher.submit_form(selector)
        if "error" in submit_result:
            result["submitted"] = False
            result["submit_error"] = submit_result["error"]
            result["element_id"] = element_id
        else:
            self.fetcher.wait_for_load(timeout_ms=10000)
            result["submitted"] = True
            result["strategy"] = submit_result.get("strategy")
            try:
                url = self.fetcher.evaluate("window.location.href", quiet=True)
                if not url.startswith("error"):
                    result["url_after"] = url
            except Exception:
                pass
            try:
                time.sleep(0.5)
                html = self.fetcher.content()
                if html:
                    current_url = self.fetcher.current_url() or tab.url
                    tab.url = current_url
                    tab.page = build_page(html, current_url, current_url)
                    result["page"] = page_to_dict(tab.page)
            except Exception as e:
                _logger.warn("fill_and_submit", f"Page rebuild failed after submit: {e}", "error")
                result["page_error"] = str(e)
        return result

    def _evaluate(self, js_code: str, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        try:
            result = self.fetcher.evaluate(js_code)
            return _ok(result=result)
        except Exception as e:
            return _err(str(e))

    def get_console_logs(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return _ok(logs=self.fetcher.get_console_logs())

    def _get_full_text(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        try:
            text = self.fetcher.get_full_text()
            return _ok(url=tab.url if tab else None, text=text)
        except Exception as e:
            return _err(str(e))

    def _screenshot(self, path: str | None = None, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        try:
            data = self.fetcher.screenshot(path)
            if data is None:
                return _err("no page loaded")
            if path:
                return _ok(screenshot=path)
            return _ok(screenshot_base64=base64.b64encode(data).decode())
        except Exception as e:
            return _err(str(e))

    def _press_key(self, key: str, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.press_key(key)

    def _clipboard_copy(self, text: str, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.clipboard_copy(text)

    def _clipboard_read(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.clipboard_read()

    def _highlight(self, eids: list[int], tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.highlight_elements(eids)

    def _search(self, query: str, tab_id: int | None = None) -> dict[str, Any]:
        _logger.info("search", query)
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&udm=14"
        if tab_id is None:
            tab = self.session.create_tab()
            self.fetcher.create_page(tab.id)
            return self._navigate(url, tab_id=tab.id)
        return self._navigate(url, tab_id=tab_id)

    def _clear_cookies(self) -> dict[str, Any]:
        try:
            self.fetcher.clear_cookies()
            return _ok(cleared=True)
        except Exception as e:
            return _err(str(e))

    def _back(self) -> dict[str, Any]:
        MAX_DEPTH = 10
        for _ in range(MAX_DEPTH):
            try:
                nav_result = self.fetcher.go_back()
                if "error" in nav_result:
                    return _ok(back=False, error=nav_result["error"])
                self.fetcher.wait_for_load(timeout_ms=5000)
                html = self.fetcher.content()
                url = self.fetcher.current_url()
                tab = self.session.active_tab
                if tab and html and not url.startswith("chrome-error:"):
                    tab.url = url
                    tab.page = build_page(html, url, url)
                    return _ok(back=True, url=url)
                if url.startswith("chrome-error:") or url in ("about:blank", ""):
                    continue
                return _ok(back=True, url=url)
            except Exception as e:
                return _ok(back=False, error=str(e))
        return _ok(back=False, error="too many error pages in history")

    def _forward(self) -> dict[str, Any]:
        MAX_DEPTH = 10
        for _ in range(MAX_DEPTH):
            try:
                nav_result = self.fetcher.go_forward()
                if "error" in nav_result:
                    return _ok(forward=False, error=nav_result["error"])
                self.fetcher.wait_for_load(timeout_ms=5000)
                html = self.fetcher.content()
                url = self.fetcher.current_url()
                tab = self.session.active_tab
                if tab and html and not url.startswith("chrome-error:"):
                    tab.url = url
                    tab.page = build_page(html, url, url)
                    return _ok(forward=True, url=url)
                if url.startswith("chrome-error:") or url in ("about:blank", ""):
                    continue
                return _ok(forward=True, url=url)
            except Exception as e:
                return _ok(forward=False, error=str(e))
        return _ok(forward=False, error="too many error pages in history")

    # -- Tab management -----------------------------------------------------

    def _tab_new(self) -> dict[str, Any]:
        tab = self.session.create_tab()
        self.fetcher.create_page(tab.id)
        return _ok(tab_id=tab.id, tabs=len(self.session.tabs))

    def _tab_switch(self, tab_id: int) -> dict[str, Any]:
        if not self.session.switch_tab(tab_id):
            return _err(f"No tab with ID {tab_id}")
        if not self.fetcher.set_active_tab(tab_id):
            return _err(f"Browser page not found for tab {tab_id}")
        return _ok(tab_id=tab_id)

    def _tab_close(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            if not self.session.switch_tab(tab_id):
                return _err(f"No tab with ID {tab_id}")
        tab = self.session.active_tab
        if tab and self.session.close_tab(tab.id):
            self.fetcher.close_page(tab.id)
            new_active = self.session.active_tab
            if new_active and not self.fetcher.set_active_tab(new_active.id):
                self.fetcher.create_page(new_active.id)
            return _ok(
                tab_id=tab.id,
                closed=True,
                active_tab_id=new_active.id if new_active else None,
                tabs=len(self.session.tabs),
            )
        return _err("Cannot close last tab")

    def _refresh(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            if not self.session.switch_tab(tab_id):
                return _err(f"No tab with ID {tab_id}")
        tab = self.session.active_tab
        if tab and tab.url and tab.url != "about:blank":
            self._page_cache.invalidate(tab.url)
            return self._navigate(tab.url, tab_id=tab.id)
        return _err("No page to refresh")

    def _get_page(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if tab and tab.page:
            return _ok(tab_id=tab.id, page=page_to_dict(tab.page))
        return _ok(page=None)

    def _expand(self, section_id: int, tab_id: int | None = None, minimal: bool | None = None) -> dict[str, Any]:
        if minimal is None:
            minimal = True
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return _err("No page loaded")
        cache = _build_section_cache(tab.page)
        section = cache.get(section_id)
        if not section:
            return _err(f"No section with ID {section_id}")
        section.collapsed = False
        result: dict[str, Any] = _ok(tab_id=tab.id, expanded=section_id)
        if not minimal:
            result["page"] = page_to_dict(tab.page)
        return result

    def _collapse(self, section_id: int, tab_id: int | None = None, minimal: bool | None = None) -> dict[str, Any]:
        if minimal is None:
            minimal = True
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return _err("No page loaded")
        cache = _build_section_cache(tab.page)
        section = cache.get(section_id)
        if not section:
            return _err(f"No section with ID {section_id}")
        section.collapsed = True
        result: dict[str, Any] = _ok(tab_id=tab.id, collapsed=section_id)
        if not minimal:
            result["page"] = page_to_dict(tab.page)
        return result

    def _get_section(self, section_id: int, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return _err("No page loaded")
        cache = _build_section_cache(tab.page)
        section = cache.get(section_id)
        if not section:
            return _err(f"No section with ID {section_id}")
        result = section_to_dict(section)
        result["full_content"] = section.full_content or section.content or ""
        full_parts = [result["full_content"]]
        def _collect(subs):
            for sub in subs:
                fc = sub.full_content or sub.content or ""
                if fc:
                    full_parts.append(fc)
                _collect(sub.subsections)
        _collect(section.subsections)
        result["full_content"] = "\n\n".join(full_parts)
        return _ok(section=result)

    def _wait_for_element(self, selector: str, timeout_ms: int = 10000, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.wait_for_element(selector, int(timeout_ms))

    def _status(self) -> dict[str, Any]:
        tab = self.session.active_tab
        logs = self.fetcher.peek_console_logs()
        result = _ok(
            tabs=len(self.session.tabs),
            active_tab=self.session.active_tab_id,
            current_url=tab.url if tab else None,
            can_go_back=self.fetcher.can_go_back(),
            can_go_forward=self.fetcher.can_go_forward(),
            cache_size=self._page_cache.size(),
        )
        if logs:
            result["console_logs"] = logs
        return result

    def close(self) -> None:
        self.session.save()
        _logger.flush()
        self.fetcher.close()


def _build_section_cache(page) -> dict[int, Section]:
    cache: dict[int, Section] = {}

    def _walk(secs: list[Section]) -> None:
        for s in secs:
            cache[s.section_id] = s
            _walk(s.subsections)

    if page:
        _walk(page.sections)
    return cache


def _find_section(sections, section_id: int):
    for s in sections:
        if s.section_id == section_id:
            return s
        found = _find_section(s.subsections, section_id)
        if found:
            return found
    return None


if __name__ == "__main__":
    api = SurfboardAPI()
    print("Surfboard API ready", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = api.handle(request)
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError as e:
            print(json.dumps(_err(f"Invalid JSON: {e}")), flush=True)
        except Exception as e:
            print(json.dumps(_err(str(e))), flush=True)
    api.close()

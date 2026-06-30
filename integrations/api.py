from __future__ import annotations

import base64
import inspect
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from surfboard.browser import BrowserFetcher
from surfboard.models import ElementType, Session
from surfboard.serializers import page_to_dict, section_to_dict
from surfboard.tree import build_page

from integrations.url_rewrite import reddit_json_to_html, rewrite_url


def _css_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _log(tool: str, detail: str, status: str = "ok") -> None:
    log_dir = Path.home() / ".surfboard"
    log_dir.mkdir(exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "tool": tool, "detail": detail, "status": status}
    with open(log_dir / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class SurfboardAPI:
    def __init__(self) -> None:
        self.fetcher = BrowserFetcher()
        self.session = Session()
        self.session.create_tab()

    _HANDLERS: dict[str, tuple[str, list[str]]] = {}  # cmd -> (method_name, param_keys)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    _DISPATCH: dict[str, tuple[str, dict[str, Any]]] | None = None

    def _get_dispatch(self) -> dict[str, tuple[str, dict[str, Any]]]:
        if self._DISPATCH is not None:
            return self._DISPATCH
        dispatch = {
            "navigate": ("_navigate", {"url": "", "tab_id": None, "push_history": True}),
            "open": ("_navigate", {"url": "", "tab_id": None, "push_history": True}),
            "click": ("_click", {"target": "", "tab_id": None, "minimal": True, "id": 0}),
            "search": ("_search", {"query": ""}),
            "fill": ("_fill", {"id": 0, "text": "", "tab_id": None}),
            "fill_and_submit": ("_fill_and_submit", {"id": 0, "text": "", "tab_id": None}),
            "hover": ("_hover", {"id": 0, "tab_id": None}),
            "scroll_to": ("_scroll_to", {"id": 0, "tab_id": None}),
            "scroll_by": ("_scroll_by", {"x": 0, "y": 0, "tab_id": None}),
            "wait_for_load": ("_wait_for_load", {"timeout_ms": 10000, "tab_id": None}),
            "wait_for_element": ("_wait_for_element", {"selector": "", "timeout_ms": 10000, "tab_id": None}),
            "back": ("_back", {}),
            "forward": ("_forward", {}),
            "tab_new": ("_tab_new", {}),
            "tab_switch": ("_tab_switch", {"id": 0}),
            "tab_close": ("_tab_close", {"tab_id": None}),
            "refresh": ("_refresh", {}),
            "page": ("_get_page", {"tab_id": None}),
            "get_page": ("_get_page", {"tab_id": None}),
            "status": ("_status", {}),
            "evaluate": ("_evaluate", {"js": "", "tab_id": None}),
            "get_full_text": ("_get_full_text", {"tab_id": None}),
            "screenshot": ("_screenshot", {"path": None, "tab_id": None}),
            "press_key": ("_press_key", {"key": "", "tab_id": None}),
            "clipboard_copy": ("_clipboard_copy", {"text": "", "tab_id": None}),
            "clipboard_read": ("_clipboard_read", {"tab_id": None}),
            "highlight": ("_highlight", {"ids": [], "tab_id": None}),
            "get_section": ("_get_section", {"id": 0, "tab_id": None}),
            "expand": ("_expand", {"id": 0, "tab_id": None, "minimal": True}),
            "collapse": ("_collapse", {"id": 0, "tab_id": None, "minimal": True}),
            "clear_cookies": ("_clear_cookies", {}),
        }
        SurfboardAPI._DISPATCH = dispatch
        return dispatch

    _PARAM_ALIASES = {"id": "target"}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = request.get("cmd", request.get("method", ""))
        params = request.get("params", request.get("arguments", {})).copy()

        for alias_from, alias_to in self._PARAM_ALIASES.items():
            if alias_from in params and alias_to not in params:
                params[alias_to] = params[alias_from]

        dispatch = self._get_dispatch()
        entry = dispatch.get(cmd)
        if entry is None:
            return {
                "error": f"Unknown command: {cmd!r}",
                "hint": (
                    "Available: browse(url), search(query), click(id), "
                    "fill(id, text), fill_and_submit(id, text), hover(id), "
                    "scroll_to(id), scroll_by(x, y), wait_for_load(timeout_ms), "
                    "get_page(), get_full_text(), evaluate(js), back(), forward(), "
                    "refresh(), tab_new(), tab_switch(tab_id), screenshot(), "
                    "highlight(ids), press_key(key), clipboard_copy(text), "
                    "clipboard_read()."
                ),
            }

        method_name, param_spec = entry
        kwargs = {}
        for key, default in param_spec.items():
            raw = params.get(key)
            kwargs[key] = raw if raw is not None else default

        method = getattr(self, method_name)
        sig = inspect.signature(method)
        filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return method(**filtered)

    def _navigate(self, url: str, tab_id: int | None = None, push_history: bool = True) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        url, rewrite_note = rewrite_url(url)

        result = self.fetcher.fetch(url)
        if result.error:
            _log("browse", url, "error")
            return {"error": result.error}

        if rewrite_note == "reddit-json":
            html = reddit_json_to_html(result.html, result.final_url)
        else:
            html = result.html

        page = build_page(html, url, result.final_url)
        _log("browse", result.final_url)

        # Use specified tab, or reuse the active tab (create one only if none exists)
        if tab_id is not None:
            if not self.session.switch_tab(tab_id):
                return {"error": f"No tab with ID {tab_id}"}
            tab = self.session.active_tab
        else:
            tab = self.session.active_tab
            if not tab:
                tab = self.session.create_tab()

        if tab:
            tab.url = result.final_url
            tab.page = page
            if push_history:
                tab.push_url(result.final_url)

        return {"tab_id": tab.id if tab else None, "page": page_to_dict(page)}

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
        return tag

    def _build_fallback_selectors(self, el) -> list[str]:
        """Generate alternative selectors for hard-to-click elements."""
        fallbacks = []
        tag = "div"
        if el.type == ElementType.BUTTON:
            tag = "button"
        elif el.type == ElementType.TEXT_INPUT:
            tag = "input"
        elif el.type == ElementType.TEXTAREA:
            tag = "textarea"

        # Try aria-label
        if el.attributes.get("aria-label"):
            fallbacks.append(f"{tag}[aria-label={_css_quote(el.attributes['aria-label'])}]")

        # Try title attribute
        if el.attributes.get("title"):
            fallbacks.append(f"{tag}[title={_css_quote(el.attributes['title'])}]")

        # Try class-based selector (first class)
        el_class = el.attributes.get("class", "")
        if el_class:
            classes = el_class.strip().split()
            if classes:
                class_sel = "".join(f".{c}" for c in classes[:2])
                fallbacks.append(f"{tag}{class_sel}")

        # Try role attribute
        if el.attributes.get("role"):
            fallbacks.append(f"{tag}[role={_css_quote(el.attributes['role'])}]")

        # Try visible text content for buttons/links
        if el.text and el.type in (ElementType.BUTTON, ElementType.LINK):
            text = el.text.strip()[:50]
            if text:
                fallbacks.append(f"{tag}:has-text({_css_quote(text)})")

        # Last resort: click by element text
        if el.text and el.type == ElementType.BUTTON:
            text = el.text.strip()[:30]
            if text:
                fallbacks.append(f"text={text}")

        return fallbacks

    def _click(self, target: str, tab_id: int | None = None, minimal: bool | None = None) -> dict[str, Any]:
        if minimal is None:
            minimal = True
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return {"error": "No page loaded"}

        target = target.replace("#", "")
        if target.isdigit():
            eid = int(target)
            el = tab.page.element_by_id(eid)
            if not el:
                return {"error": f"No element with ID {eid}"}
            if el.href:
                return self._navigate(el.href, tab_id=tab.id)

            selector = self._build_selector(el)
            fallbacks = self._build_fallback_selectors(el)
            click_result = self.fetcher.click(selector, fallback_selectors=fallbacks)
            if "error" in click_result:
                return {**click_result, "element_id": eid, "hint": "The page DOM may have changed. Use get_page() to refresh."}
            self.fetcher.wait_for_load(timeout_ms=1000)
            html = self.fetcher.content()
            url = self.fetcher.current_url() or tab.url
            if html and not minimal:
                tab.url = url
                tab.page = build_page(html, tab.url, url)
            elif html:
                tab.url = url
            result: dict[str, Any] = {"clicked": el.id, "type": el.type.value, "label": el.label, "selector": click_result.get("selector_used", selector)}
            if not minimal and tab and tab.page:
                result["page"] = page_to_dict(tab.page)
            return result

        return {"error": f"Invalid target: {target}"}

    def _fill(self, element_id: int, text: str, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return {"error": "No page loaded"}
        el = tab.page.element_by_id(element_id)
        if not el:
            return {"error": f"No element with ID {element_id}"}
        if el.type not in (ElementType.TEXT_INPUT, ElementType.TEXTAREA, ElementType.SELECT):
            return {"error": f"Element {element_id} is not a text input (type: {el.type.value})"}
        selector = self._build_selector(el)
        if el.type == ElementType.SELECT:
            result = self.fetcher.select_option(selector, text)
        else:
            result = self.fetcher.fill(selector, text)
        if "error" in result:
            return result
        el.value = text
        _log("fill", f"[{element_id}] {el.label}")
        return {"filled": element_id, "label": el.label, "value": text, "selector": selector}

    def _hover(self, element_id: int, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return {"error": "No page loaded"}
        el = tab.page.element_by_id(element_id)
        if not el:
            return {"error": f"No element with ID {element_id}"}
        selector = self._build_selector(el)
        result = self.fetcher.hover(selector)
        if "error" in result:
            result["element_id"] = element_id
            result["hint"] = "The page DOM may have changed since this element was loaded. Use get_page() to refresh the element list."
            return result
        return {"hovered": element_id, "label": el.label, "selector": selector}

    def _scroll_to(self, element_id: int, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return {"error": "No page loaded"}
        el = tab.page.element_by_id(element_id)
        if not el:
            return {"error": f"No element with ID {element_id}"}
        selector = self._build_selector(el)
        result = self.fetcher.scroll_to(selector)
        if "error" in result:
            result["element_id"] = element_id
            result["hint"] = "The page DOM may have changed since this element was loaded. Use get_page() to refresh the element list."
            return result
        return {"scrolled_to": element_id, "label": el.label, "selector": selector}

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
        if tab_id is not None:
            self.session.switch_tab(tab_id)

        tab = self.session.active_tab
        el = tab.page.element_by_id(element_id) if tab and tab.page else None
        selector = self._build_selector(el) if el else None

        submit_result = self.fetcher.submit_form(selector)
        if "error" in submit_result:
            result["submitted"] = False
            result["submit_error"] = submit_result["error"]
            result["element_id"] = element_id
        else:
            # Wait a moment for the page to respond
            time.sleep(0.5)
            try:
                self.fetcher.wait_for_load(timeout_ms=2000)
            except Exception:
                pass
            result["submitted"] = True
            result["strategy"] = submit_result.get("strategy")
            url = self.fetcher.evaluate("window.location.href")
            if not url.startswith("error"):
                result["url_after"] = url
            # Update tab page if navigation happened
            try:
                html = self.fetcher.content()
                if html:
                    current_url = self.fetcher.current_url() or tab.url
                    if current_url != tab.url:
                        tab.url = current_url
                        tab.page = build_page(html, current_url, current_url)
                        tab.push_url(current_url)
                        result["page"] = page_to_dict(tab.page)
            except Exception:
                pass
        return result

    def _evaluate(self, js_code: str, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        try:
            result = self.fetcher.evaluate(js_code)
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    def _get_full_text(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        try:
            text = self.fetcher.get_full_text()
            return {"url": tab.url if tab else None, "text": text}
        except Exception as e:
            return {"error": str(e)}

    def _screenshot(self, path: str | None = None, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        try:
            data = self.fetcher.screenshot(path)
            if data is None:
                return {"error": "no page loaded"}
            if path:
                return {"screenshot": path}
            return {"screenshot_base64": base64.b64encode(data).decode()}
        except Exception as e:
            return {"error": str(e)}

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

    def _search(self, query: str) -> dict[str, Any]:
        _log("search", query)
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&udm=14"
        return self._navigate(url)

    def _clear_cookies(self) -> dict[str, Any]:
        """Clear all cookies for the current browser context."""
        try:
            self.fetcher._context.clear_cookies()
            # Also clear the saved cookie file
            cookie_path = self.fetcher._cookie_path()
            if cookie_path.exists():
                cookie_path.unlink()
            return {"cleared": True}
        except Exception as e:
            return {"error": str(e)}

    def _back(self) -> dict[str, Any]:
        tab = self.session.active_tab
        if tab and tab.can_go_back():
            tab.go_back()
            result = self._navigate(tab.history[tab.history_index], tab_id=tab.id, push_history=False)
            result["back"] = True
            return result
        return {"back": False}

    def _forward(self) -> dict[str, Any]:
        tab = self.session.active_tab
        if tab and tab.can_go_forward():
            tab.go_forward()
            result = self._navigate(tab.history[tab.history_index], tab_id=tab.id, push_history=False)
            result["forward"] = True
            return result
        return {"forward": False}

    def _tab_new(self) -> dict[str, Any]:
        tab = self.session.create_tab()
        return {"tab_id": tab.id, "tabs": len(self.session.tabs)}

    def _tab_switch(self, tab_id: int) -> dict[str, Any]:
        if self.session.switch_tab(tab_id):
            return {"tab_id": tab_id}
        return {"error": f"No tab with ID {tab_id}"}

    def _tab_close(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            if not self.session.switch_tab(tab_id):
                return {"error": f"No tab with ID {tab_id}"}
        tab = self.session.active_tab
        if tab and self.session.close_tab(tab.id):
            new_active = self.session.active_tab
            return {
                "tab_id": tab.id,
                "closed": True,
                "active_tab_id": new_active.id if new_active else None,
                "tabs": len(self.session.tabs),
            }
        return {"error": "Cannot close last tab"}

    def _refresh(self) -> dict[str, Any]:
        tab = self.session.active_tab
        if tab and tab.url and tab.url != "about:blank":
            return self._navigate(tab.url, tab_id=tab.id)
        return {"error": "No page to refresh"}

    def _get_page(self, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if tab and tab.page:
            return {"tab_id": tab.id, "page": page_to_dict(tab.page)}
        return {"page": None}

    def _expand(self, section_id: int, tab_id: int | None = None, minimal: bool | None = None) -> dict[str, Any]:
        if minimal is None:
            minimal = True
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return {"error": "No page loaded"}
        section = _find_section(tab.page.sections, section_id)
        if not section:
            return {"error": f"No section with ID {section_id}"}
        section.collapsed = False
        result: dict[str, Any] = {"tab_id": tab.id, "expanded": section_id}
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
            return {"error": "No page loaded"}
        section = _find_section(tab.page.sections, section_id)
        if not section:
            return {"error": f"No section with ID {section_id}"}
        section.collapsed = True
        result: dict[str, Any] = {"tab_id": tab.id, "collapsed": section_id}
        if not minimal:
            result["page"] = page_to_dict(tab.page)
        return result

    def _get_section(self, section_id: int, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        tab = self.session.active_tab
        if not tab or not tab.page:
            return {"error": "No page loaded"}
        section = _find_section(tab.page.sections, section_id)
        if not section:
            return {"error": f"No section with ID {section_id}"}
        result = section_to_dict(section)
        result["full_content"] = section.full_content or section.content or ""
        # Collect all subsection content recursively
        full_parts = [result["full_content"]]
        def _collect(subs):
            for sub in subs:
                fc = sub.full_content or sub.content or ""
                if fc:
                    full_parts.append(fc)
                _collect(sub.subsections)
        _collect(section.subsections)
        result["full_content"] = "\n\n".join(full_parts)
        return {"section": result}

    def _wait_for_element(self, selector: str, timeout_ms: int = 10000, tab_id: int | None = None) -> dict[str, Any]:
        if tab_id is not None:
            self.session.switch_tab(tab_id)
        return self.fetcher.wait_for_element(selector, int(timeout_ms))

    def _status(self) -> dict[str, Any]:
        tab = self.session.active_tab
        logs = self.fetcher.peek_console_logs()
        result = {
            "tabs": len(self.session.tabs),
            "active_tab": self.session.active_tab_id,
            "current_url": tab.url if tab else None,
            "can_go_back": tab.can_go_back() if tab else False,
            "can_go_forward": tab.can_go_forward() if tab else False,
        }
        if logs:
            result["console_logs"] = logs
        return result

    def close(self) -> None:
        self.fetcher.close()


def _find_section(sections, section_id: int):
    for s in sections:
        if s.section_id == section_id:
            return s
        found = _find_section(s.subsections, section_id)
        if found:
            return found
    return None


def run_server() -> None:
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
            print(json.dumps({"error": f"Invalid JSON: {e}"}), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)
    api.close()


if __name__ == "__main__":
    run_server()

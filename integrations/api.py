from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from surfboard.browser import BrowserFetcher
from surfboard.models import ElementType, Session
from surfboard.tree import build_page


import re as _re

_REDDIT_RE = _re.compile(r"https?://(?:www\.|old\.)?reddit\.com(/[^\s]*)")
_MEDIUM_RE = _re.compile(r"https?://(?:www\.)?medium\.com(/[^\s]*)")
_TWITTER_RE = _re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com(/[^\s]*)")
_AMP_RE = _re.compile(r"(https?://[^\s]+?)/amp/?$", _re.IGNORECASE)


def _css_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _rewrite_url(url: str) -> tuple[str, str | None]:
    """Return (rewritten_url, note). note is set if the URL was rewritten."""
    # Reddit → JSON API (no CAPTCHA, structured data)
    m = _REDDIT_RE.match(url)
    if m:
        path = m.group(1).rstrip("/")
        if not path.endswith(".json"):
            return f"https://www.reddit.com{path}.json?raw_json=1", "reddit-json"

    # Twitter/X → nitter (no JS wall)
    m = _TWITTER_RE.match(url)
    if m:
        return f"https://nitter.net{m.group(1)}", "nitter-mirror"

    # Medium → scribe.rip mirror (no paywall/JS wall)
    m = _MEDIUM_RE.match(url)
    if m:
        return f"https://scribe.rip{m.group(1)}", "scribe-mirror"

    # AMP URLs → strip /amp suffix to get canonical page
    m = _AMP_RE.match(url)
    if m:
        return m.group(1), "amp-stripped"

    return url, None



def _log(tool: str, detail: str, status: str = "ok") -> None:
    log_dir = Path.home() / ".surfboard"
    log_dir.mkdir(exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "tool": tool, "detail": detail, "status": status}
    with open(log_dir / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _reddit_json_to_html(raw: str, url: str) -> str:
    """Convert Reddit JSON API response to simple HTML for build_page."""
    try:
        data = json.loads(raw)
    except Exception:
        return raw

    parts: list[str] = []

    def post_html(post: dict) -> str:
        title = post.get("title", "")
        author = post.get("author", "")
        score = post.get("score", "")
        selftext = post.get("selftext", "")
        link = post.get("url", "")
        permalink = "https://www.reddit.com" + post.get("permalink", "")
        h = f"<h1><a href='{permalink}'>{title}</a></h1>"
        h += f"<p>by u/{author} · {score} points</p>"
        if selftext:
            h += f"<p>{selftext}</p>"
        elif link:
            h += f"<p><a href='{link}'>{link}</a></p>"
        return h

    def comment_html(node: dict, depth: int = 0) -> str:
        if node.get("kind") == "more":
            return ""
        d = node.get("data", node)
        author = d.get("author", "[deleted]")
        body = d.get("body", "")
        score = d.get("score", "")
        tag = f"h{min(depth + 2, 6)}"
        h = f"<{tag}>u/{author} ({score} pts)</{tag}><p>{body}</p>"
        replies = d.get("replies", {})
        if isinstance(replies, dict):
            for child in replies.get("data", {}).get("children", []):
                h += comment_html(child, depth + 1)
        return h

    if isinstance(data, dict) and data.get("kind") == "Listing":
        for child in data.get("data", {}).get("children", []):
            parts.append(post_html(child.get("data", {})))
    elif isinstance(data, list) and len(data) == 2:
        for child in data[0].get("data", {}).get("children", []):
            parts.append(post_html(child.get("data", {})))
        parts.append("<h2>Comments</h2>")
        for child in data[1].get("data", {}).get("children", []):
            parts.append(comment_html(child))

    return "<html><body>" + "\n".join(parts) + "</body></html>" if parts else raw


class SurfboardAPI:
    def __init__(self) -> None:
        self.fetcher = BrowserFetcher()
        self.session = Session()
        self.session.create_tab()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = request.get("cmd", "")
        params = request.get("params", {})

        if cmd == "navigate" or cmd == "open":
            return self._navigate(params.get("url", ""))
        elif cmd == "click":
            return self._click(params.get("id", "") or params.get("target", ""), minimal=params.get("minimal", False))
        elif cmd == "search":
            return self._search(params.get("query", ""))
        elif cmd == "fill":
            return self._fill(params.get("id", 0), params.get("text", ""), tab_id=params.get("tab_id"))
        elif cmd == "hover":
            return self._hover(params.get("id", 0), tab_id=params.get("tab_id"))
        elif cmd == "scroll_to":
            return self._scroll_to(params.get("id", 0), tab_id=params.get("tab_id"))
        elif cmd == "scroll_by":
            return self._scroll_by(params.get("x", 0), params.get("y", 0), tab_id=params.get("tab_id"))
        elif cmd == "wait_for_load":
            return self._wait_for_load(params.get("timeout_ms", 10000), tab_id=params.get("tab_id"))
        elif cmd == "back":
            return self._back()
        elif cmd == "forward":
            return self._forward()
        elif cmd == "tab_new":
            return self._tab_new()
        elif cmd == "tab_switch":
            return self._tab_switch(params.get("id", 0))
        elif cmd == "tab_close":
            return self._tab_close()
        elif cmd == "refresh":
            return self._refresh()
        elif cmd == "page":
            return self._get_page()
        elif cmd == "status":
            return self._status()
        elif cmd == "evaluate":
            return self._evaluate(params.get("js", ""), tab_id=params.get("tab_id"))
        elif cmd == "get_full_text":
            return self._get_full_text(tab_id=params.get("tab_id"))
        elif cmd == "screenshot":
            return self._screenshot(path=params.get("path"), tab_id=params.get("tab_id"))
        elif cmd == "fill_and_submit":
            return self._fill_and_submit(params.get("id", 0), params.get("text", ""), tab_id=params.get("tab_id"))
        elif cmd == "press_key":
            return self._press_key(params.get("key", ""), tab_id=params.get("tab_id"))
        elif cmd == "clipboard_copy":
            return self._clipboard_copy(params.get("text", ""), tab_id=params.get("tab_id"))
        elif cmd == "clipboard_read":
            return self._clipboard_read(tab_id=params.get("tab_id"))
        elif cmd == "highlight":
            return self._highlight(params.get("ids", []), tab_id=params.get("tab_id"))
        else:
            return {
                "error": f"Unknown command: {cmd!r}",
                "hint": (
                    "Use explicit tool calls instead of natural-language commands. "
                    "Available actions: browse(url), search(query), click(id), "
                    "fill(id, text), fill_and_submit(id, text), hover(id), "
                    "scroll_to(id), scroll_by(x, y), wait_for_load(timeout_ms), "
                    "get_page(), get_full_text(), evaluate(js), back(), forward(), "
                    "refresh(), tab_new(), tab_switch(tab_id), screenshot(), "
                    "highlight(ids), press_key(key), clipboard_copy(text), "
                    "clipboard_read()."
                ),
            }

    def _navigate(self, url: str, tab_id: int | None = None, push_history: bool = True) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        url, rewrite_note = _rewrite_url(url)

        result = self.fetcher.fetch(url)
        if result.error:
            _log("browse", url, "error")
            return {"error": result.error}

        if rewrite_note == "reddit-json":
            html = _reddit_json_to_html(result.html, result.final_url)
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

        return {"tab_id": tab.id if tab else None, "page": _page_to_dict(page)}

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
                result["page"] = _page_to_dict(tab.page)
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
            import time
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
                        from surfboard.tree import build_page
                        tab.url = current_url
                        tab.page = build_page(html, current_url, current_url)
                        tab.push_url(current_url)
                        result["page"] = _page_to_dict(tab.page)
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
            import base64
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
        import urllib.parse
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
            return {"tab_id": tab.id, "page": _page_to_dict(tab.page)}
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
            result["page"] = _page_to_dict(tab.page)
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
            result["page"] = _page_to_dict(tab.page)
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
        result = _section_to_dict(section)
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


def _page_to_dict(page) -> dict[str, Any]:
    d: dict[str, Any] = {"u": page.url, "t": page.title}
    if page.description:
        d["d"] = page.description
    d["s"] = [_section_to_dict(s) for s in page.sections]
    d["e"] = [_element_to_dict(e) for e in page.elements]
    return d


def _section_to_dict(section) -> dict[str, Any]:
    d: dict[str, Any] = {"i": section.section_id, "t": section.title, "l": section.level}
    if section.collapsed:
        d["c"] = True
    if not section.collapsed and section.content:
        d["ct"] = section.content
    if section.subsections:
        d["ss"] = [_section_to_dict(s) for s in section.subsections]
    return d


_ELEMENT_LABEL_MAX = 80


def _element_to_dict(el) -> dict[str, Any]:
    d: dict[str, Any] = {"i": el.id, "t": el.type.value}
    if el.label:
        label = el.label
        if len(label) > _ELEMENT_LABEL_MAX:
            label = label[:_ELEMENT_LABEL_MAX].rsplit(" ", 1)[0] + "…"
        d["l"] = label
    if el.href:
        d["h"] = el.href
    if el.name:
        d["n"] = el.name
    if el.placeholder:
        d["p"] = el.placeholder
    if el.value:
        d["v"] = el.value
    return d


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

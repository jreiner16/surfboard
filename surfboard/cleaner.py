from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from readability import Document


def clean_html(html: str, source_url: str) -> tuple[str, list[dict]]:
    if not html.strip():
        return "", []

    full_soup = BeautifulSoup(html, "lxml")

    try:
        doc = Document(html)
        summary_html = doc.summary()
        title = doc.title() or ""
    except Exception:
        summary_html = ""
        title = ""

    text = ""
    if summary_html:
        soup = BeautifulSoup(summary_html, "lxml")
        for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

    if not text:
        for tag in full_soup(["script", "style", "noscript", "iframe", "svg"]):
            tag.decompose()
        text = full_soup.get_text(separator="\n", strip=True)

    elements = _extract_elements(full_soup, source_url)

    return text, elements


SKIP_EXTENSIONS = {".css", ".js", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".woff2", ".ttf"}
SKIP_DOMAINS = {"doubleclick.net", "googlesyndication.com", "googleadservices.com", "facebook.com/tr"}
SKIP_HREF_PATTERNS = [re.compile(p) for p in [
    r"duckduckgo\.com/y\.js",
    r"google\.com/aclk",
    r"bing\.com/aclick",
]]

_DDG_REDIRECT_RE = re.compile(r"https?://(?:www\.)?duckduckgo\.com/l/\?uddg=(.+?)(?:&|$)")
_GOOGLE_REDIRECT_RE = re.compile(r"https?://(?:www\.)?google\.com/url\?q=(.+?)(?:&|$)")


def _unwrap_redirect(url: str) -> str:
    import urllib.parse
    m = _DDG_REDIRECT_RE.match(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    m = _GOOGLE_REDIRECT_RE.match(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url


def _is_tracking(href: str) -> bool:
    for domain in SKIP_DOMAINS:
        if domain in href:
            return True
    for pat in SKIP_HREF_PATTERNS:
        if pat.search(href):
            return True
    return False


def _parent_has_ad_class(tag) -> bool:
    parent = tag.parent
    for _ in range(5):
        if not parent:
            break
        cls = parent.get("class", [])
        if isinstance(cls, list) and any("ad" in (c or "").lower() for c in cls):
            return True
        parent = parent.parent
    return False


def _extract_elements(soup: BeautifulSoup, base_url: str) -> list[dict]:
    elements = []
    seen = set()
    eid = 1

    for selector, etype in [
        ("a[href]", "link"),
        ("button", "button"),
        ("input:not([type=hidden])", "text_input"),
        ("textarea", "textarea"),
        ("select", "select"),
    ]:
        for tag in soup.select(selector):
            text = tag.get_text(strip=True)
            href = tag.get("href", "") if tag.name == "a" else ""

            if tag.name == "a" and not text and not tag.get("aria-label"):
                continue
            if tag.name == "a" and href:
                ext = href.rsplit(".", 1)[-1].lower() if "." in href else ""
                if ext in SKIP_EXTENSIONS:
                    continue
                if _is_tracking(href):
                    continue
                if _parent_has_ad_class(tag):
                    continue
                if len(href) > 300:
                    continue

            key = (str(tag.name), href, str(tag.get("id", "")), str(tag.get("name", "")), text)
            if key in seen:
                continue
            seen.add(key)

            el = {"id": eid, "type": etype, "tag": tag.name}
            el["text"] = text

            if isinstance(tag, Tag):
                el["attributes"] = {k: v for k, v in tag.attrs.items() if isinstance(v, str)}

            if tag.name == "a":
                resolved = urljoin(base_url, href) if href else None
                if resolved:
                    resolved = _unwrap_redirect(resolved)
                el["href"] = resolved

            if tag.name == "input":
                el["name"] = tag.get("name")
                el["placeholder"] = tag.get("placeholder")
                el["value"] = tag.get("value")
                input_type = tag.get("type", "text")
                if input_type in ("checkbox", "radio"):
                    el["type"] = input_type

            if tag.name == "textarea":
                el["name"] = tag.get("name")
                el["placeholder"] = tag.get("placeholder")

            if tag.name == "select":
                el["name"] = tag.get("name")
                options = tag.find_all("option")
                el["options"] = [
                    {"value": o.get("value", ""), "text": o.get_text(strip=True)}
                    for o in options
                ]

            if tag.name == "button":
                el["name"] = tag.get("name")
                el["value"] = tag.get("value")

            elements.append(el)
            eid += 1

    return elements


def extract_metadata(soup: BeautifulSoup) -> dict:
    meta = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name", tag.get("property", ""))
        content = tag.get("content", "")
        if name and content:
            meta[name] = content
    return meta

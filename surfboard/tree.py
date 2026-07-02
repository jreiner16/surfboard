from __future__ import annotations

from typing import Iterator

from bs4 import BeautifulSoup, Tag
from surfboard.cleaner import clean_html
from surfboard.models import Element, ElementType, Page, Section

SECTION_CHAR_LIMIT = 5000
PREVIEW_CHARS = 800


def build_page(html: str, url: str, final_url: str) -> Page:
    text, raw_elements, soup = clean_html(html, url)

    page = Page(url=final_url, title=_extract_title(soup))

    desc = _extract_description(soup)
    if desc:
        page.description = desc

    seen_ids: set[int] = set()
    elements: list[Element] = []
    for raw in raw_elements:
        etype = ElementType(raw["type"])
        el = Element(
            id=raw["id"],
            type=etype,
            text=raw.get("text", ""),
            href=raw.get("href"),
            name=raw.get("name"),
            placeholder=raw.get("placeholder"),
            value=raw.get("value"),
            tag=raw.get("tag", ""),
            attributes=raw.get("attributes", {}),
        )
        if raw["id"] not in seen_ids:
            seen_ids.add(raw["id"])
            elements.append(el)

    page.elements = elements

    sections, _ = _build_sections(soup, elements, text)
    _assign_elements_to_sections(sections, elements, soup)
    page.sections = sections

    if not sections and text.strip():
        page.sections = [
            Section(
                title="Page Content",
                level=1,
                content=text,
                full_content=text,
                elements=page.elements,
                section_id=1,
            )
        ]

    return page


def _extract_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(separator=" ", strip=True)
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(separator=" ", strip=True)
    return ""


def _extract_description(soup: BeautifulSoup) -> str:
    for tag in soup.find_all("meta"):
        name = tag.get("name", tag.get("property", "")).lower()
        if name in ("description", "og:description"):
            return tag.get("content", "")
    return ""


def _build_sections(
    soup: BeautifulSoup, elements: list[Element], text: str
) -> tuple[list[Section], list[Element]]:
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])

    if not headings:
        return [], elements

    section_id_gen = iter(range(1, 1 << 31))

    sections: list[Section] = []
    for i, h in enumerate(headings):
        level = int(h.name[1])
        title = h.get_text(separator=" ", strip=True)
        if not title:
            continue

        content_parts: list[str] = []
        sibling = h.find_next_sibling()
        while sibling and sibling.name not in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if sibling.name in ("script", "style", "noscript"):
                sibling = sibling.find_next_sibling()
                continue
            content_parts.append(sibling.get_text(separator=" ", strip=True))
            sibling = sibling.find_next_sibling()

        content = " ".join(content_parts)

        section = Section(
            title=title,
            level=level,
            content=_truncate_text(content),
            full_content=content,
            section_id=next(section_id_gen),
        )

        if level > 1:
            for s in reversed(sections):
                if s.level < level:
                    s.subsections.append(section)
                    break
            else:
                sections.append(section)
        else:
            sections.append(section)

    _assign_elements_to_sections(sections, elements, soup)
    _mark_collapsed(sections, section_id_gen)

    return sections, elements


def _assign_elements_to_sections(
    sections: list[Section], elements: list[Element], soup: BeautifulSoup
) -> None:
    if not elements or not sections:
        return

    headings = [
        h for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        if h.get_text(strip=True)
    ]
    if not headings:
        return

    # Build flat section list in heading order (tree traversal) so elements
    # are assigned by position, not by heading text (avoids duplicate-title bugs).
    flat_sections: list[Section] = []
    def _walk(secs: list[Section]) -> None:
        for s in secs:
            flat_sections.append(s)
            _walk(s.subsections)
    _walk(sections)

    el_tags: list[Tag] = []
    for selector in ("a[href]", "button", "input:not([type=hidden])", "textarea", "select"):
        el_tags.extend(soup.select(selector))

    # Build O(1) lookup dict for elements
    el_lookup: dict[tuple, list[Element]] = {}
    for el in elements:
        key = (el.tag, el.text, el.href or "", el.attributes.get("id", ""), el.name or "")
        el_lookup.setdefault(key, []).append(el)

    heading_idx = 0
    for el_tag in el_tags:
        if heading_idx >= len(headings) or heading_idx >= len(flat_sections):
            break

        while heading_idx + 1 < len(headings):
            nxt = headings[heading_idx + 1]
            nxt_line = getattr(nxt, "sourceline", None)
            el_line = getattr(el_tag, "sourceline", None)
            nxt_pos = getattr(nxt, "sourcepos", None)
            el_pos = getattr(el_tag, "sourcepos", None)
            if nxt_line is not None and el_line is not None:
                if nxt_line < el_line:
                    heading_idx += 1
                elif nxt_line == el_line and nxt_pos is not None and el_pos is not None and nxt_pos < el_pos:
                    heading_idx += 1
                else:
                    break
            else:
                break

        section = flat_sections[heading_idx]

        tag_text = el_tag.get_text(strip=True)
        tag_href = el_tag.get("href", "") if el_tag.name == "a" else ""
        tag_id = str(el_tag.get("id", ""))
        tag_name = str(el_tag.get("name", ""))

        key = (el_tag.name, tag_text, tag_href, tag_id, tag_name)
        for el in el_lookup.get(key, []):
            if el not in section.elements:
                section.elements.append(el)
                break


def _mark_collapsed(sections: list[Section], counter: Iterator[int], depth: int = 0) -> None:
    for section in sections:
        if section.subsections:
            section.collapsed = False
            _mark_collapsed(section.subsections, counter, depth + 1)
        elif section.content and len(section.content) > PREVIEW_CHARS:
            section.collapsed = False
            preview = section.content[:PREVIEW_CHARS].rsplit(" ", 1)[0] + "…"
            rest = section.content[len(preview) - 1:].lstrip()
            section.content = preview
            more = Section(
                title="Continue reading",
                level=section.level + 1,
                content=rest,
                section_id=next(counter),
            )
            more.collapsed = True
            section.subsections.append(more)
        else:
            section.collapsed = False


def _truncate_text(text: str, limit: int = SECTION_CHAR_LIMIT) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    result: list[str] = []
    char_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if char_count + len(stripped) > limit:
            remaining = limit - char_count
            if remaining > 40:
                result.append(stripped[:remaining] + "...")
            break
        result.append(stripped)
        char_count += len(stripped) + 1
    return "\n".join(result)

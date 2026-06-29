from __future__ import annotations

from typing import Iterator

from bs4 import BeautifulSoup, Tag
from surfboard.cleaner import clean_html
from surfboard.models import Element, ElementType, Page, Section

SECTION_CHAR_LIMIT = 3000
CHUNK_SIZE = 600  # chars per content chunk subsection
CHUNK_LINES = 8   # lines per content chunk subsection


def build_page(html: str, url: str, final_url: str) -> Page:
    text, raw_elements = clean_html(html, url)

    soup = BeautifulSoup(html, "lxml")

    page = Page(url=final_url, title=_extract_title(soup))

    desc = _extract_description(soup)
    if desc:
        page.description = desc

    seen_ids: set[int] = set()
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
            page.elements.append(el)

    sections, body_elements = _build_sections(soup, page.elements, text)
    page.sections = sections

    if not sections and text.strip():
        page.sections = [
            Section(
                title="Page Content",
                level=1,
                content=_truncate_text(text),
                full_content=text,
                elements=page.elements,
            )
        ]

    return page


def _extract_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
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
        title = h.get_text(strip=True)
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
        if len(content) > SECTION_CHAR_LIMIT:
            content = content[:SECTION_CHAR_LIMIT] + "..."

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
    for section in sections:
        _chunk_content_into_subsections(section, section_id_gen)
    _mark_collapsed(sections, section_id_gen)

    return sections, elements


def _assign_elements_to_sections(
    sections: list[Section], elements: list[Element], soup: BeautifulSoup
) -> None:
    for section in sections:
        _assign_elements_to_sections(section.subsections, elements, soup)


PREVIEW_CHARS = 300


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


def _chunk_content_into_subsections(section: Section, counter: Iterator[int]) -> None:
    """If a section has long content and no subsections, split content into chunk subsections."""
    for sub in section.subsections:
        _chunk_content_into_subsections(sub, counter)

    if section.subsections:
        return  # already has real subsections, don't chunk

    lines = [l for l in section.content.splitlines() if l.strip()] if section.content else []
    if len(lines) <= CHUNK_LINES:
        return  # short enough, no need to chunk

    chunks: list[list[str]] = []
    for i in range(0, len(lines), CHUNK_LINES):
        chunks.append(lines[i:i + CHUNK_LINES])

    section.content = ""
    for i, chunk in enumerate(chunks):
        sub = Section(
            title=f"Part {i + 1}",
            level=section.level + 1,
            content="\n".join(chunk),
            section_id=next(counter),
        )
        section.subsections.append(sub)


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

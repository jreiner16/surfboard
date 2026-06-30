from __future__ import annotations

from typing import Any

from surfboard.models import Element, Page, Section

_ELEMENT_LABEL_MAX = 80


def page_to_dict(page: Page) -> dict[str, Any]:
    d: dict[str, Any] = {"u": page.url, "t": page.title}
    if page.description:
        d["d"] = page.description
    d["s"] = [section_to_dict(s) for s in page.sections]
    d["e"] = [element_to_dict(e) for e in page.elements]
    return d


def section_to_dict(section: Section) -> dict[str, Any]:
    d: dict[str, Any] = {"i": section.section_id, "t": section.title, "l": section.level}
    if section.collapsed:
        d["c"] = True
    if not section.collapsed and section.content:
        d["ct"] = section.content
    if section.subsections:
        d["ss"] = [section_to_dict(s) for s in section.subsections]
    return d


def element_to_dict(el: Element) -> dict[str, Any]:
    d: dict[str, Any] = {"i": el.id, "t": el.type.value}
    if el.label:
        label = el.label
        if len(label) > _ELEMENT_LABEL_MAX:
            label = label[:_ELEMENT_LABEL_MAX].rsplit(" ", 1)[0] + "\u2026"
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

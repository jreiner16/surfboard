from __future__ import annotations

from surfboard.models import ElementType, Page, Tab


def render_page(tab: Tab, page: Page) -> list[str]:
    lines: list[str] = []
    lines.append(f"==[ Tab {tab.id} | {page.title} ]==")
    lines.append(f"URL: {page.url}")
    if page.description:
        lines.append(f"Desc: {page.description}")

    lines.append("")
    lines.append("-- Content --")
    for section in page.sections:
        _render_section(section, lines, depth=0)

    has_actions = bool(page.elements)
    if has_actions:
        lines.append("")
        lines.append("-- Actions --")
        _render_actions(page, lines)


    return lines


def _render_section(section, lines: list[str], depth: int = 0) -> None:
    indent = "  " * depth
    if section.collapsed:
        sub_hint = f" [{len(section.subsections)} subsections]" if section.subsections else ""
        lines.append(f"{indent}[{section.section_id}] + {section.title}{sub_hint}  (expand {section.section_id})")
    else:
        lines.append(f"{indent}[{section.section_id}] - {section.title}")
        if section.content:
            content_lines = section.content.splitlines()
            # Show up to 4 lines as preview; hint if more
            preview = content_lines[:4]
            for cl in preview:
                if cl.strip():
                    lines.append(f"{indent}  {cl}")
            if len(content_lines) > 4:
                lines.append(f"{indent}  ... ({len(content_lines) - 4} more lines, expand {section.section_id} to read)")
        for sub in section.subsections:
            _render_section(sub, lines, depth + 1)


def _render_actions(page: Page, lines: list[str]) -> None:
    if not page.elements:
        return

    links = [e for e in page.elements if e.type == ElementType.LINK and e.href]
    buttons = [e for e in page.elements if e.type == ElementType.BUTTON and (e.label or "").strip()]
    inputs = [e for e in page.elements if e.type in (ElementType.TEXT_INPUT, ElementType.TEXTAREA, ElementType.SELECT) and (e.label or e.placeholder or e.name)]
    others = [e for e in page.elements if e.type not in (ElementType.LINK, ElementType.BUTTON, ElementType.TEXT_INPUT, ElementType.TEXTAREA, ElementType.SELECT) and (e.label or "").strip()]

    if links:
        lines.append("  Navigate:")
        for el in links[:15]:
            label = (el.label or el.href or "")
            if len(label) > 65:
                label = label[:62] + "..."
            tag_hint = f" ({el.tag})" if el.tag and el.tag != "a" else ""
            lines.append(f"    [{el.id:>3}] click  {label}{tag_hint}")

    if buttons:
        lines.append("  Buttons:")
        for el in buttons[:10]:
            label = (el.label or "")[:50]
            hints = []
            if el.attributes.get("aria-label"):
                hints.append(f"aria-label='{el.attributes['aria-label']}'")
            if el.attributes.get("title"):
                hints.append(f"title='{el.attributes['title']}'")
            hint_str = f" ({', '.join(hints)})" if hints else ""
            lines.append(f"    [{el.id:>3}] click  {label}{hint_str}")

    if inputs:
        lines.append("  Inputs:")
        for el in inputs[:10]:
            label = (el.label or el.placeholder or el.name or "")[:50]
            hints = []
            if el.attributes.get("aria-label"):
                hints.append(f"aria-label='{el.attributes['aria-label']}'")
            if el.attributes.get("title"):
                hints.append(f"title='{el.attributes['title']}'")
            input_type = el.attributes.get("type", "")
            if input_type and input_type != "text":
                hints.append(f"type={input_type}")
            hint_str = f" ({', '.join(hints)})" if hints else ""
            lines.append(f"    [{el.id:>3}] type <text> in  {label}{hint_str}")

    if others:
        lines.append("  Other:")
        for el in others[:5]:
            label = (el.label or "")[:40]
            hints = []
            if el.attributes.get("aria-label"):
                hints.append(f"aria-label='{el.attributes['aria-label']}'")
            if el.tag and el.tag not in ("input", "textarea", "select", "button", "a"):
                hints.append(f"tag={el.tag}")
            hint_str = f" ({', '.join(hints)})" if hints else ""
            lines.append(f"    [{el.id:>3}] {el.type.value}  {label}{hint_str}")

    if len(links) > 15 or len(buttons) > 10 or len(inputs) > 10:
        n_extra = max(0, len(links) - 15) + max(0, len(buttons) - 10) + max(0, len(inputs) - 10)
        lines.append(f"  ... and {n_extra} more elements")


def render_status_bar(tab: Tab) -> list[str]:
    nav = ("<" if tab.can_go_back() else "-") + (" >" if tab.can_go_forward() else " -")
    return [f"Tab {tab.id}/{len(tab.history) if tab.history else 1} {nav} {tab.url}"]


def render_error(msg: str) -> str:
    return f"Error: {msg}"


def render_info(msg: str) -> str:
    return f"{msg}"


def render_help() -> list[str]:
    return [
        "Commands:",
        "  open <url>              Navigate to a URL",
        "  click <n>               Click element by ID (link or button)",
        "  search <q>              Search the web via Google",
        "  type <text> in <n>      Fill an input field by ID",
        "  back / forward          Navigate history",
        "  tab new / tab <n>       Tab management",
        "  expand/collapse <n|all> Expand or collapse sections",
        "  refresh / help / quit",
    ]

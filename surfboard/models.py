from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class ElementType(str, Enum):
    LINK = "link"
    BUTTON = "button"
    TEXT_INPUT = "text_input"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"


@dataclass
class Element:
    id: int
    type: ElementType
    text: str = ""
    href: Optional[str] = None
    name: Optional[str] = None
    placeholder: Optional[str] = None
    value: Optional[str] = None
    tag: str = ""
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.text:
            return self.text.strip() or (self.placeholder or "")
        if self.placeholder:
            return f"[{self.placeholder}]"
        if self.name:
            return f"<{self.name}>"
        return f"<{self.tag}>"


@dataclass
class Section:
    title: str
    level: int = 1
    content: str = ""
    section_id: int = 0
    elements: list[Element] = field(default_factory=list)
    subsections: list[Section] = field(default_factory=list)
    collapsed: bool = False
    collapsed_by_default: bool = False
    full_content: str = ""


@dataclass
class Page:
    url: str
    title: str = ""
    description: str = ""
    sections: list[Section] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)

    def element_by_id(self, eid: int) -> Optional[Element]:
        for el in self.elements:
            if el.id == eid:
                return el
        return None


@dataclass
class Tab:
    id: int
    url: str = "about:blank"
    page: Optional[Page] = None
    scroll_position: int = 0
    expanded_sections: set[int] = field(default_factory=set)
    elements_expanded: bool = True


@dataclass
class Session:
    _tabs: dict[int, Tab] = field(default_factory=dict)
    active_tab_id: int = 0
    next_tab_id: int = 1
    _recent_tabs: list[int] = field(default_factory=list)

    @property
    def tabs(self) -> list[Tab]:
        return list(self._tabs.values())

    @property
    def active_tab(self) -> Optional[Tab]:
        return self._tabs.get(self.active_tab_id)

    def create_tab(self) -> Tab:
        tab = Tab(id=self.next_tab_id)
        self.next_tab_id += 1
        self._tabs[tab.id] = tab
        if self.active_tab_id:
            self._recent_tabs.append(self.active_tab_id)
        self.active_tab_id = tab.id
        return tab

    def close_tab(self, tab_id: int) -> bool:
        if len(self._tabs) <= 1:
            return False
        del self._tabs[tab_id]
        self._recent_tabs = [t for t in self._recent_tabs if t in self._tabs]
        if self.active_tab_id == tab_id:
            if self._recent_tabs:
                self.active_tab_id = self._recent_tabs.pop()
            elif self._tabs:
                self.active_tab_id = next(iter(self._tabs))
        return True

    def switch_tab(self, tab_id: int) -> bool:
        if tab_id in self._tabs:
            if self.active_tab_id in self._recent_tabs:
                self._recent_tabs.remove(self.active_tab_id)
            self._recent_tabs.append(self.active_tab_id)
            self.active_tab_id = tab_id
            return True
        return False

    def _session_path(self) -> Path:
        return Path.home() / ".surfboard" / "session.json"

    def save(self) -> None:
        """Persist session (tabs, scroll positions) to disk."""
        data = {
            "active_tab_id": self.active_tab_id,
            "next_tab_id": self.next_tab_id,
            "tabs": [
                {
                    "id": t.id,
                    "url": t.url,
                    "scroll_position": t.scroll_position,
                    "expanded_sections": list(t.expanded_sections),
                }
                for t in self._tabs.values()
            ],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def restore(self) -> bool:
        """Restore session from disk. Returns True if a session was found."""
        path = self._session_path()
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            self.active_tab_id = data.get("active_tab_id", 0)
            self.next_tab_id = data.get("next_tab_id", 1)
            self._tabs.clear()
            for td in data.get("tabs", []):
                tab = Tab(
                    id=td["id"],
                    url=td.get("url", "about:blank"),
                    scroll_position=td.get("scroll_position", 0),
                    expanded_sections=set(td.get("expanded_sections", [])),
                )
                self._tabs[tab.id] = tab
            return True
        except Exception:
            return False

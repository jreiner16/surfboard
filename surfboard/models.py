from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ElementType(str, Enum):
    LINK = "link"
    BUTTON = "button"
    TEXT_INPUT = "text_input"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    IMAGE = "image"
    HEADING = "heading"


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
    history: list[str] = field(default_factory=list)
    history_index: int = -1
    scroll_position: int = 0
    expanded_sections: set[int] = field(default_factory=set)
    elements_expanded: bool = True

    def can_go_back(self) -> bool:
        return self.history_index > 0

    def can_go_forward(self) -> bool:
        return self.history_index < len(self.history) - 1

    def go_back(self) -> Optional[str]:
        if not self.can_go_back():
            return None
        self.history_index -= 1
        return self.history[self.history_index]

    def go_forward(self) -> Optional[str]:
        if not self.can_go_forward():
            return None
        self.history_index += 1
        return self.history[self.history_index]

    def push_url(self, url: str) -> None:
        if self.history_index >= 0 and self.history_index < len(self.history) - 1:
            self.history = self.history[: self.history_index + 1]
        self.history.append(url)
        self.history_index = len(self.history) - 1


@dataclass
class Session:
    _tabs: dict[int, Tab] = field(default_factory=dict)
    active_tab_id: int = 0
    next_tab_id: int = 1

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
        self.active_tab_id = tab.id
        return tab

    def close_tab(self, tab_id: int) -> bool:
        if len(self._tabs) <= 1:
            return False
        del self._tabs[tab_id]
        if self.active_tab_id == tab_id and self._tabs:
            self.active_tab_id = list(self._tabs.keys())[-1]
        return True

    def switch_tab(self, tab_id: int) -> bool:
        if tab_id in self._tabs:
            self.active_tab_id = tab_id
            return True
        return False

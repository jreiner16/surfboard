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


class Intent(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    SEARCH = "search"
    BACK = "back"
    FORWARD = "forward"
    SCROLL = "scroll"
    TAB_NEW = "tab_new"
    TAB_SWITCH = "tab_switch"
    TAB_CLOSE = "tab_close"
    EXPAND = "expand"
    COLLAPSE = "collapse"
    FILL = "fill"
    SUBMIT = "submit"
    REFRESH = "refresh"
    HELP = "help"
    QUIT = "quit"
    UNKNOWN = "unknown"


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

    def total_lines(self) -> int:
        lines = len(self.content.splitlines()) if self.content else 0
        for sub in self.subsections:
            lines += sub.total_lines()
        return lines


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
    tabs: list[Tab] = field(default_factory=list)
    active_tab_id: int = 0
    next_tab_id: int = 1

    @property
    def active_tab(self) -> Optional[Tab]:
        for t in self.tabs:
            if t.id == self.active_tab_id:
                return t
        return None

    def create_tab(self) -> Tab:
        tab = Tab(id=self.next_tab_id)
        self.next_tab_id += 1
        self.tabs.append(tab)
        self.active_tab_id = tab.id
        return tab

    def close_tab(self, tab_id: int) -> bool:
        if len(self.tabs) <= 1:
            return False
        self.tabs = [t for t in self.tabs if t.id != tab_id]
        if self.active_tab_id == tab_id and self.tabs:
            self.active_tab_id = self.tabs[-1].id
        return True

    def switch_tab(self, tab_id: int) -> bool:
        for t in self.tabs:
            if t.id == tab_id:
                self.active_tab_id = tab_id
                return True
        return False


@dataclass
class Command:
    intent: Intent
    slots: dict[str, str] = field(default_factory=dict)
    raw: str = ""

    def slot(self, name: str, default: str = "") -> str:
        return self.slots.get(name, default)

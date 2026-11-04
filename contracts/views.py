"""Views: read-only data a module offers interfaces for their pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

from contracts.commands import LEVELS
from contracts.shared import NAME

VIEW_MAX = 1_000_000  # bytes of JSON a view may give once encoded


class ViewError(Exception):
    """Why a view could not be read: `unknown` (no such view, or a persona it does not cover), `forbidden` (below
    its access), `failed` (it raised or took too long) or `too_big` (more than VIEW_MAX)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class View:
    """Read-only data a module offers pages about a persona, too big for a fact (a star map, the state of a settings
    panel): worked out when a page asks and never stored, so asking again costs only the work. Changes are never made
    through a view; they are capabilities, which the core checks and records.

    `read(persona, person)` gives JSON, at most VIEW_MAX once encoded; `person` is `(interface, sender id)`, who asks.
    `access` is the lowest level that may read it (`creator`, the owner; `admin`; `member`, anyone the interface
    lets in), checked the way a command's is. `personas` limits it to these (empty: any persona the core has).
    Interfaces read it as `<module>.<name>` with `InterfacePort.view`."""

    name: str
    read: Callable[[str, tuple[str, str]], Awaitable[Any]]
    description: str = ""
    access: str = "creator"
    personas: Sequence[str] = ()
    timeout_s: float = 10.0

    def __post_init__(self):
        if not NAME.fullmatch(self.name or ""):
            raise ValueError(f"view {self.name!r}: a name is lowercase letters, digits and _")
        if not callable(self.read):
            raise ValueError(f"view {self.name!r}: read is an async function (persona, person)")
        if self.access not in LEVELS:
            raise ValueError(f"view {self.name!r}: access is one of {', '.join(LEVELS)}")
        personas = (self.personas,) if isinstance(self.personas, str) else self.personas
        if not all(isinstance(item, str) and item for item in personas):
            raise ValueError(f"view {self.name!r}: personas is a list of names")
        object.__setattr__(self, "personas", tuple(personas))
        if not isinstance(self.timeout_s, (int, float)) or isinstance(self.timeout_s, bool) or self.timeout_s <= 0:
            raise ValueError(f"view {self.name!r}: timeout_s is seconds, above 0")

"""The log: what happened in a conversation, one line each, kept by the core.

    the core, after each write or critical action that ran ───────────────► a line of kind `action`
    engines read `session.logbook` (MomoChat shows the last few lines in each turn); people read `$log`

Lines are never edited. It is not the audit log, the core's own record for the owner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contracts import LogEntry

if TYPE_CHECKING:
    from core.manager.manager import Manager

MAX_TEXT = 500
LINES_KEPT = 2000  # in one conversation; the oldest go


class LogbookHandle:
    """Implements contracts.Logbook for one conversation."""

    def __init__(self, manager: "Manager", address: str):
        self._manager, self._address = manager, address

    def recent(self, limit: int = 8, kind: str = "") -> list[LogEntry]:
        return self._manager.tank.log_lines(self._address, max(1, min(int(limit), 50)), kind=kind)[::-1]

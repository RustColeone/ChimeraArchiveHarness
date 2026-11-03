"""When each thread began: a conversation's, one persona's in it, and hers everywhere (the tank's `core:threads`).

A thread is what a speaker reads of a conversation: what came after its last start. Engines start one over with
`Session.start_over`, commands with `ToolContext.start_over`, and everyone reads the result the same way.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from core.storage.tank import Tank

THREADS = "core:threads"


def thread_key(address: str = "", persona: str = "") -> str:
    """Where a start is kept: this conversation's (`address`), hers in it (both), or hers everywhere (`persona`)."""
    return json.dumps([address, persona], ensure_ascii=False)


class Threads:
    def __init__(self, tank: "Tank"):
        self.store = tank.store(THREADS)

    def start(self, at: float, address: str = "", persona: str = "") -> None:
        self.store.set(thread_key(address, persona), at)

    def since(self, address: str, personas: Iterable[str]) -> float:
        """When the thread of these personas in this conversation began: the latest start that holds them (0: never)."""
        keys = [thread_key(address), *(key for persona in personas
                                       for key in (thread_key(address, persona), thread_key("", persona)))]
        return max(float(self.store.get(key) or 0) for key in keys)

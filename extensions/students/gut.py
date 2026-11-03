"""A student's gut (mneme-llm's `gut`): one for each student, and her turns between her reading and her note."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from pathlib import Path

from contracts import ModelRequest

from mneme_llm.gut import Gut, Turn

WAITING = 64  # turns kept between her reading and her note


class Guts:
    def __init__(self, folder: Path, starters: dict[str, Path] | None = None):
        self.folder, self.starters = Path(folder), dict(starters or {})
        self.opened: dict[str, Gut] = {}
        self.turns: OrderedDict[tuple[str, str], Turn] = OrderedDict()

    def of(self, persona: str) -> Gut:
        if persona not in self.opened:
            self.opened[persona] = Gut(self.folder / f"{persona}.db", self.starters.get(persona))
        return self.opened[persona]

    def begin(self, context, subject: str) -> Turn | None:
        """Her turn, or None until her gut has woken (the first message after a start: it wakes beside it)."""
        persona, trigger = context.persona, context.trigger
        gut = self.of(persona.name)
        if not gut.awake:
            if gut.waking is None or gut.waking.done():
                gut.waking = asyncio.ensure_future(asyncio.to_thread(gut.wake))
            return None

        async def ask(messages: list[dict], tokens: int, timeout: float = 30.0) -> str:
            return (await context.models.generate(ModelRequest(messages, persona=persona.name, effort="none",
                                                               max_tokens=tokens, timeout_s=timeout))).text
        turn = self.turns[(persona.name, trigger.id)] = Turn(gut, ask, persona.prompt, trigger.text, subject)
        while len(self.turns) > WAITING:
            self.turns.popitem(last=False)
        return turn

    async def learn(self, exchange, context) -> None:
        """A watcher: after she has answered, her note and what this person is making of her. It never holds up a reply."""
        turn = self.turns.pop((exchange.persona.name, exchange.trigger.id), None)
        if turn is not None and await turn.learn(exchange.text) is None:
            context.log("gut_no_note", persona=exchange.persona.name)

    def close(self) -> None:
        for gut in self.opened.values():
            gut.close()

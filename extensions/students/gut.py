"""A student's gut (mneme-llm's `gut`): one for each student, and her turns between her reading and her note."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections import OrderedDict
from pathlib import Path

from contracts import ModelRequest

from mneme_llm.gut import Gut, Turn

WAITING = 64  # turns kept between her reading and her note


class Busy:
    """Blocking work on her files running in threads (her gut waking, her pages), so that closing them waits for it:
    closing a file under a thread still using it can crash SQLite. Once closing, no new work starts."""

    def __init__(self):
        self._count, self._closing, self._idle = 0, False, threading.Condition()

    async def run(self, work, *arguments):
        def counted():
            with self._idle:
                if self._closing:
                    raise RuntimeError("her files are closing")
                self._count += 1
            try:
                return work(*arguments)
            finally:
                with self._idle:
                    self._count -= 1
                    self._idle.notify_all()
        return await asyncio.to_thread(counted)

    def close(self, timeout_s: float) -> bool:
        """Let no new work start, and wait for what is running (at most `timeout_s`): whether it all finished."""
        with self._idle:
            self._closing = True
            return self._idle.wait_for(lambda: self._count == 0, timeout_s)


class Guts:
    """`person`: whose account a subject is (`Book.person`), so her gut knows a person once, on all their accounts, as
    her memory does."""

    def __init__(self, folder: Path, starters: dict[str, Path] | None = None, person=None):
        self.folder, self.starters = Path(folder), dict(starters or {})
        self.person = person or (lambda subject: subject)
        self.opened: dict[str, Gut] = {}
        self.busy = Busy()
        self.turns: OrderedDict[tuple[str, str], Turn] = OrderedDict()

    def close(self) -> None:
        """Close every gut file opened (when the core stops), under its lock (see Book.close)."""
        for gut in self.opened.values():
            with getattr(gut, "lock", None) or contextlib.nullcontext():
                gut.close()
        self.opened.clear()

    def of(self, persona: str) -> Gut:
        if persona not in self.opened:
            self.opened[persona] = Gut(self.folder / f"{persona}.db", self.starters.get(persona))
        return self.opened[persona]

    def wake(self, gut: Gut) -> asyncio.Future:
        """Her waking, the one under way or a new one (it takes a while: it reads what she was born with), and then the
        accounts she knew apart that are one person joined."""
        def waking():
            gut.wake()
            self.join(gut)
        if gut.waking is None or gut.waking.done():
            gut.waking = asyncio.ensure_future(self.busy.run(waking))
        return gut.waking

    def join(self, gut: Gut) -> int:
        """Each account her gut knows that is another account of someone's, joined to them (`Gut.link`): how many."""
        known = {*gut.net.people, *gut.languages, *gut.settings["people"], *(row[0] for row in gut.sightings)}
        known |= {row[0] for row in gut.db.execute("select distinct subject from lessons where subject != ''")}
        return sum(gut.link(subject, self.person(subject)) for subject in sorted(known)
                   if self.person(subject) != subject)

    def relink(self) -> None:
        """Someone linked another account: every gut that is awake joins it now (one waking later joins it then)."""
        for gut in self.opened.values():
            if gut.awake:
                self.join(gut)

    async def woken(self, persona: str) -> Gut:
        """Her gut, awake."""
        gut = self.of(persona)
        if not gut.awake:
            await asyncio.shield(self.wake(gut))
        return gut

    def begin(self, context, subject: str, language: str = "") -> Turn | None:
        """Her turn, or None until her gut has woken (the first message after a start: it wakes beside it). `language`
        is the one she answers in, whatever they write in ("": theirs)."""
        persona, trigger = context.persona, context.trigger
        gut = self.of(persona.name)
        if not gut.awake:
            self.wake(gut)
            return None

        async def ask(messages: list[dict], tokens: int, timeout: float = 30.0) -> str:
            return (await context.models.generate(ModelRequest(messages, persona=persona.name, effort="none",
                                                               max_tokens=tokens, timeout_s=timeout))).text
        turn = self.turns[(persona.name, trigger.id)] = Turn(gut, ask, persona.prompt, trigger.text,
                                                             self.person(subject), language)
        while len(self.turns) > WAITING:
            self.turns.popitem(last=False)
        return turn

    async def learn(self, exchange, context) -> None:
        """A watcher: after she has answered, her note and what this person is making of her. It never holds up a reply."""
        turn = self.turns.pop((exchange.persona.name, exchange.trigger.id), None)
        if turn is not None and await turn.learn(exchange.text) is None:
            context.log("gut_no_note", persona=exchange.persona.name)

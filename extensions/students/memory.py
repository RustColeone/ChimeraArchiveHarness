"""A student's memory: what she keeps of each person, in mneme-llm (one file per student). A student is an agent with this
memory, so it is part of what the students module adds.

Every engine that places prompt parts (MomoChat) tells her, each turn, who the person is to her, what they call her,
her notes for the message, what was said before that bears on it (word for word: her look), her mood's news and how
her classmates seem today; and in a chat with her alone it reads what she keeps of the person (her surface) in place of
its own window. After each of her messages a watcher lets her learn from it: the exchange kept word for word, how it
left her feeling, what is worth remembering, and a day of contact for her closeness with the person. Two tools let her
search everything said before with the person, and read an exchange with its neighbours, when her look does not have
it. What was said in a group chat, every student there heard: the exchange and the notes one keeps of it go into each
classmate's file too; a direct chat stays between the two. A person with several accounts (`people:`, or linked with
`$link`) is one person to every student. Pages see where she stands with you as facts (bond, alias, mood, plans, what
she calls you, your accounts). `$alias` names a student your way, `$callme` says what the students call you, `$link`
joins another account of yours, `$bond` shows where each stands with you, `$card` is her Character Card (her
creator's alone: who she is, in their words, in her system prompt once it is on), and `$new` starts over deeper than
`/new`. Agents (personas that are not students) keep nothing.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from pathlib import Path

from contracts import (IMPULSE, Capability, Command, Context, ModelRequest, Option, PromptPart, Risk, ToolResult,
                       View, Watcher, flag, impulse, impulse_line, is_command, number)

import mneme_llm
from mneme_llm.gut import GROWS
from mneme_llm.tools import SPECS, Toolbox

from .gut import Guts

RESET = {"reset", "remove", "clear", "none"}
DAY = 86400
NAME_MAX = 40  # what the students call you
CODE_S = 600  # a `$link` code lasts ten minutes
CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # (no 0/O, 1/I/L)
# The engines whose messages are conversation (Chimera's are reports on work, which teach her nothing of you).
ENGINES = ("momochat",)
# What `students: <persona>:` (or her student.yml `memory:`, under it) may set for one student, over the settings for
# all.
OWN = ("learn", "notes", "mood", "classmates", "met_role", "owner_role", "writer_profile", "reflect_after_notes", "language",
       "memory_language", "config", "call_owner", "episodes", "said", "embed", "search", "gut", "surface", "surface_days",
       "surface_floor", "surface_cap", "surface_window")
DEEPER = ("deep", "gut")  # what `$new` clears: what she remembers; and what people taught her gut
EVERYONE = "everyone"
STARTER = "gut-starter.json.gz"  # in her folder: the lessons she is born with (tools/gut_starter.py)
TOOLBOXES = 64  # the newest runs' search tools kept (each remembers what its searches showed)
REACH = 200  # messages of a conversation read for what a person said
UNANSWERED = 20  # the most of their messages one of hers answers


def conversation(engine: str, settings: "Settings") -> bool:
    """Whether messages in this engine are conversation she learns from."""
    return engine in settings.engines


def key(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


class Settings:
    def __init__(self, config, folder: Path | None = None):
        self.raw, self.folder = dict(config), folder
        self.personas = tuple(config.get("personas") or ())
        self.engines = tuple(str(name) for name in config.get("engines") or ENGINES)
        self.learn = flag(config.get("learn"), True)
        self.notes = flag(config.get("notes"), True)
        self.mood = flag(config.get("mood"), True)
        self.classmates = flag(config.get("classmates"), True)  # how the others seem today, in her turn
        self.met_role = str(config.get("met_role", "acquaintance") or "")
        self.owner_role = str(config.get("owner_role", "creator") or "")  # the bot's owner, when they first talk
        self.writer_profile = str(config.get("writer_profile") or "") or None
        self.reflect_after = int(config.get("reflect_after_notes", 5))
        self.language = str(config.get("language") or "")
        self.call_owner = str(config.get("call_owner") or "")  # what her memory calls the owner (else their name)
        self.memory_language = str(config.get("memory_language") or "") or None  # notes also glossed in it
        # What was said, word for word: each exchange kept (`episodes`), a look of `said` characters of it for each
        # message (0: none), found by meaning as well as words with `embed` (OpenAI embeddings, OPENAI_API_KEY), and
        # `search`: a search comes with it, and her tools to look through the rest.
        self.episodes = flag(config.get("episodes"), True)
        self.said = number(config.get("said"), 6000, 0, 50_000)
        self.embed = flag(config.get("embed"), True)
        self.search = flag(config.get("search"), True)
        self.gut = flag(config.get("gut"), False)  # what stays of her without her memory or her model (gut.py)
        # `surface`: with one person, she reads the newest of what is kept of them in place of the engine's window. How
        # much is mneme-llm's (`surface_days`, `surface_floor`, `surface_cap`, `surface_window`), as high as anyone likes.
        self.surface = flag(config.get("surface"), True)
        self.surface_limits = {key: config[key] for key in ("surface_days", "surface_floor", "surface_cap",
                                                            "surface_window") if config.get(key)}
        given = str(config.get("config") or "")  # a mneme-llm config file (TOML), read when her file is new
        path = Path(given).expanduser() if given else None
        self.config_file = str(path if path is None or path.is_absolute() or folder is None else folder / path) \
            if path is not None else None
        self.students = {str(name): dict(value or {}) for name, value in dict(config.get("students") or {}).items()}
        self._own: dict[str, Settings] = {}

    def of(self, persona: str) -> "Settings":
        """One student's settings: hers under `students:`, over the settings for all."""
        if persona not in self.students:
            return self
        if persona not in self._own:
            own = {key: value for key, value in self.students[persona].items() if key in OWN}
            self._own[persona] = Settings({**self.raw, **own, "students": {}}, self.folder)
        return self._own[persona]


class Book:
    """Every student's mneme-llm file, `<data>/<persona>.db` with the space `<persona>`, opened when first needed.

    A file is made only when there is something to keep: an alias, a role from the settings, or what she learns."""

    def __init__(self, folder: Path, *, personas=(), names=None, platforms=None, roles=None, people=None,
                 settings: Settings | None = None):
        self.folder, self.personas = Path(folder), tuple(personas)
        self.names = {str(name): dict(value) for name, value in dict(names or {}).items()}  # her display name and others
        self.opened: dict[str, object] = {}
        self.platforms = {str(name): str(platform) for name, platform in (platforms or {}).items()}
        self.roles = {self.named(subject): str(role) for subject, role in (roles or {}).items()}
        # One person behind several accounts (`people: {Leo: [discord:1, webui:creator]}`): their first account is
        # where every student keeps them, and the name is what her memory calls them.
        self.accounts: dict[str, list[str]] = {}  # a person's own subject → all of theirs, their own first
        self.person_of: dict[str, str] = {}
        self.person_names: dict[str, str] = {}
        for name, given in dict(people or {}).items():
            subjects = [self.named(item) for item in (given if isinstance(given, (list, tuple)) else [given])
                        if str(item or "").strip()]
            subjects = [item for index, item in enumerate(subjects) if item not in subjects[:index]]
            if not subjects or any(item in self.person_of for item in subjects):
                continue  # (an account named for two people: neither link is made)
            self.accounts[subjects[0]] = subjects
            self.person_names[subjects[0]] = str(name)
            self.person_of.update({item: subjects[0] for item in subjects})
        # What people asked the students to call them (`$callme`: "*" for every student, or one student's name) and
        # the accounts they joined themselves (`$link`), kept in people.json; `people:` wins where the two disagree.
        self.own_file = self.folder / "people.json"
        try:
            own = dict(json.loads(self.own_file.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            own = {}
        self.calls = {str(person): {str(who): str(name) for who, name in dict(names).items()}
                      for person, names in dict(own.get("calls") or {}).items() if isinstance(names, dict)}
        self.links: dict[str, str] = {}
        for account, person in dict(own.get("links") or {}).items():
            self.join(str(account), str(person))
        self.codes: dict[str, tuple[str, float]] = {}  # a `$link` code → (the person who asked for it, until when)
        self.settings = settings or Settings({})
        self.toolboxes: dict[tuple[str, str], Toolbox] = {}  # (run, student) → her search tools in that run

    def keeps(self, persona: str) -> bool:
        return persona in self.personas

    def has(self, persona: str) -> bool:
        """Whether she has a file yet."""
        return (self.folder / f"{persona}.db").exists()

    def shown(self, persona: str) -> str:
        return self.names.get(persona, {}).get("display_name") or persona

    def subject(self, interface: str, sender_id: str) -> str:
        """One person, whichever bot they talk to: `<platform>:<id>` (`whale_chan` counts as `discord`, say)."""
        return f"{self.platforms.get(interface, interface)}:{sender_id}"

    def named(self, subject) -> str:
        """A subject as the settings write it (`whale_chan:42`), as the files keep it (`discord:42`)."""
        interface, _, sender = str(subject).strip().partition(":")
        return self.subject(interface, sender) if sender else interface

    def name_of(self, subject: str) -> str:
        """The person's name in `people:` ("" for someone not named there)."""
        return self.person_names.get(self.person_of.get(subject, ""), "")

    def person(self, subject: str) -> str:
        """The person's own subject: their first account in `people:`, the account they linked from, or itself."""
        return self.person_of.get(subject, subject)

    def call(self, subject: str, who: str = "*") -> str:
        """What the person asked to be called by a student (`who`), or by every student ("*"); "" when they did not."""
        return self.calls.get(self.person(subject), {}).get(who, "")

    def set_call(self, subject: str, who: str, name: str | None) -> None:
        names = self.calls.setdefault(self.person(subject), {})
        if name:
            names[who] = name
        else:
            names.pop(who, None)
        self.save()

    def join(self, account: str, person: str) -> bool:
        """`account` is another account of `person` (to every student, from now on); False when `people:` already
        says whose it is, or it is somebody's own first account."""
        person = self.person(person)
        if account == person or account in self.person_of or account in self.accounts:
            return False
        self.links[account] = person
        self.accounts.setdefault(person, [person]).append(account)
        self.person_of.setdefault(person, person)
        self.person_of[account] = person
        for memory in self.opened.values():
            self.link(memory)
        return True

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        calls = {person: names for person, names in self.calls.items() if names}
        self.own_file.write_text(json.dumps({"calls": calls, "links": self.links}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")

    def code_for(self, subject: str) -> str:
        """A one-time code (ten minutes) that joins whichever account sends it back to this person."""
        now = time.time()
        self.codes = {code: value for code, value in self.codes.items() if value[1] > now}
        code = "".join(secrets.choice(CODE_LETTERS) for _ in range(6))
        self.codes[code] = (self.person(subject), now + CODE_S)
        return code

    def redeem(self, code: str) -> str | None:
        """The person a code was given to (it is used up), or None for a wrong or late code."""
        person, until = self.codes.pop(code.strip().upper(), ("", 0.0))
        return person if until > time.time() else None

    def people(self, subject: str) -> list[tuple[str, str]]:
        """The (interface, sender id) pairs the person a subject stands for is reached by, on every account of theirs
        (`people:`) and every interface sharing its platform: facts are published for each."""
        found = set()
        for account in self.accounts.get(self.person_of.get(subject, subject), [subject]):
            platform, _, sender = account.partition(":")
            found |= {(name, sender) for name in {platform, *(name for name, value in self.platforms.items()
                                                             if value == platform)}}
        return sorted(found)

    def known(self) -> list[str]:
        return sorted(self.personas)

    def find(self, name: str, subject: str = "") -> str | None:
        """The student a name stands for: her persona name, display name, other names, or what this person calls
        her."""
        wanted = key(name)
        for persona in self.known():
            value = self.names.get(persona, {})
            if wanted in {key(persona), key(value.get("display_name")), *map(key, value.get("aliases") or ())}:
                return persona
        for persona in self.known():
            memory = self.open(persona, create=False)
            if memory is not None and subject and key(memory.aliases.get(subject) or "") == wanted:
                return persona
        return None

    def open(self, persona: str, *, create: bool = False):
        if persona in self.opened:
            return self.opened[persona]
        path = self.folder / f"{persona}.db"
        if not path.exists() and not create and not self.roles:
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        own = self.settings.of(persona)
        # Notes are found by their words (and their glosses in `memory_language`); what was said, by meaning too
        # (`embed`: embeddings with OPENAI_API_KEY, the query's waited for a few seconds at most).
        language = own.memory_language or (mneme_llm.STORED if own.config_file else None)
        memory = mneme_llm.Mneme(str(path), persona, config=own.config_file, companion_name=self.shown(persona),
                                 display_language=own.language or mneme_llm.STORED, embed=own.embed,
                                 memory_language=language, **own.surface_limits)
        self.link(memory)
        for subject, role in self.roles.items():
            memory.relate(subject, role)  # (the same role again changes nothing)
        self.opened[persona] = memory
        return memory

    def link(self, memory) -> None:
        """Her file's links as `people:` has them: each account of a person is that person (what it kept joins
        them), and an account taken out of `people:` is its own again (what was joined stays)."""
        for subject, person in memory.people.all().items():
            if self.person_of.get(subject) != person:
                memory.unlink(subject)
        for person, subjects in self.accounts.items():
            for subject in subjects[1:]:
                if memory.person(subject) != person:
                    memory.link(subject, person)

    def stand(self, persona: str, subject: str) -> dict:
        """Where she stands with a person, as facts for the pages: bond, alias, mood (None: nothing to show)."""
        memory = self.open(persona)
        calling, accounts = self.calling(persona, subject), self.accounts.get(self.person(subject), [subject])
        own = {"called": calling if any(calling.values()) else None,  # (None: nothing asked or set)
               "accounts": list(accounts) if len(accounts) > 1 else None}
        if memory is None:
            return {"bond": None, "alias": None, "mood": None, "plans": None, **own}
        relationship = memory.relations.get(subject)
        state = memory.mood.state(subject)
        now = time.time()
        plans = sorted((note for note in memory.memory.notes(subject, kinds=["plan"])
                        if note.happened_at and now - DAY <= note.happened_at <= now + 30 * DAY),
                       key=lambda note: note.happened_at)[:8]
        return {"bond": {"role": relationship.role, "closeness": round(relationship.closeness)}
                if relationship else None,
                "alias": memory.aliases.get(subject),
                "mood": {"value": round(state.value), "face": state.face,
                         "feelings": [[name, round(value)] for name, value in state.strongest(2, above=20)]}
                if state.updated_at is not None else None,
                # what the person has coming (from yesterday to a month ahead): something to ask them about
                "plans": [{"text": note.text[:160], "at": round(note.happened_at)} for note in plans] or None, **own}

    def calling(self, persona: str, subject: str, owner: bool = True) -> dict:
        """What she calls a person, and why, the most particular first: `name` (None: their name where they write), what
        they `asked` of her (`$callme <student> <name>`), `call_owner` set for her alone (the owner), what they asked of
        `everyone` (`$callme <name>`), `call_owner` for all (the `setting`, the owner's), their name in `people:`."""
        asked, everyone = self.call(subject, persona), self.call(subject)
        alone = str(self.settings.students.get(persona, {}).get("call_owner") or "")
        setting = alone or self.settings.call_owner
        name = asked or (alone if owner else "") or everyone or (self.settings.call_owner if owner else "") \
            or self.name_of(subject)
        return {"name": name or None, "asked": asked or None, "everyone": everyone or None, "setting": setting or None}

    def publish(self, facts, persona: str, subject: str) -> None:
        stand = self.stand(persona, subject)
        for person in self.people(subject):
            for name, value in stand.items():
                facts.set(persona, name, value, person=person)

    def publish_all(self, facts) -> None:
        """At start: what the files already hold, so the pages show it before anyone talks."""
        for persona in self.known():
            memory = self.open(persona)
            if memory is None:
                continue
            subjects = {item.subject for item in memory.relations.all()} | set(memory.aliases.all())
            for subject in sorted(subjects):
                self.publish(facts, persona, subject)

    def toolbox(self, persona: str, run: str):
        """Her search tools in one run (they remember what their searches showed, so a search again brings new
        exchanges), or None when she keeps nothing of what was said."""
        memory = self.open(persona)
        if memory is None:
            return None
        key = (run, persona)
        if key not in self.toolboxes:
            while len(self.toolboxes) >= TOOLBOXES:
                del self.toolboxes[next(iter(self.toolboxes))]
            self.toolboxes[key] = Toolbox(memory)
        return self.toolboxes[key]


def no_notes(person: str, language: str) -> str:
    """Her notes when there are none yet: said all the same, so she knows her memory is kept for her (left out, a
    model tends to save what it is told with a tool of its own, which waits for the owner's approval)."""
    return f"关于{person}的笔记：（暂无）" if language.startswith("zh") else f"Notes about {person}: (none yet)"


async def _nothing(value):
    return value


# How a classmate seems, by mneme-llm's face for her mood: said as a classmate would notice it.
SEEMS = {"great": ("in high spirits", "很开心"), "good": ("happy", "开心"), "ok": ("calm", "平静"),
         "worry": ("worried", "有点担心"), "sad": ("sad", "有点难过")}
RECENT = 2 * DAY  # a classmate's mood counts as today's this long after anything moved her


def classmates_line(book: "Book", persona: str, subject: str, language: str) -> str:
    """How the others seem today with this person, from their own files (no model call); "" when none has felt
    anything lately. Her file alone is hers to change: this only reads theirs, and never makes one."""
    now, seen = time.time(), []
    for name in book.known():
        if name == persona or not book.has(name):
            continue
        state = book.open(name).mood.state(subject)
        if state.updated_at is not None and now - state.updated_at <= RECENT:
            seen.append((book.shown(name), SEEMS.get(state.face, (state.face, state.face))))
    if not seen:
        return ""
    if language.startswith("zh"):
        return "（" + "，".join(f"{name}今天看起来{word[1]}" for name, word in seen) + "。）"
    return "(" + "; ".join(f"{name} seems {word[0]} today" for name, word in seen) + ".)"


def called(book: Book, persona: str, subject: str, owner: bool, sender) -> str:
    """What her memory calls the person: `Book.calling`, else the name they have where they wrote."""
    return book.calling(persona, subject, owner)["name"] or sender.name or sender.id


def where(address) -> str:
    """The conversation an exchange was said in, as her memory names it."""
    return str(address)


async def hear(book: Book, settings: Settings, exchange, subject: str, said) -> list[str]:
    """What was said in a group chat, every student there heard: each classmate keeps the exchange word for word too.
    Returns the classmates who keep it."""
    heard = []
    for persona in exchange.personas:
        own = settings.of(persona)
        if persona == exchange.persona.name or not book.keeps(persona) or not (own.learn and own.episodes):
            continue
        await book.open(persona, create=True).episodes.akeep(subject, said, conversation=where(exchange.address),
                                                             at=exchange.at)
        heard.append(persona)
    return heard


def share(book: Book, settings: Settings, exchange, subject: str, notes, facts) -> list[str]:
    """What was said in a group chat (a conversation with several students), every student there heard: the notes
    one kept of it are kept in each classmate's file as well, as her own (source "heard"). A direct chat stays
    between the two. Returns the classmates who keep them."""
    heard = []
    for persona in exchange.personas:
        own = settings.of(persona)
        if persona == exchange.persona.name or not book.keeps(persona) or not (own.learn and own.notes):
            continue
        memory = book.open(persona, create=True)
        for note in notes:
            memory.remember(subject, note.text, kind=note.kind, key=note.key, importance=note.importance,
                            feeling=note.feeling, happened_at=note.happened_at, source="heard", gloss=note.gloss)
        book.publish(facts, persona, subject)
        heard.append(persona)
    return heard


def make_part(book: Book, settings: Settings, guts: Guts | None = None):
    async def text(context) -> str:
        """Who the person is to her, what they call her, her notes for this message, what was said before that bears
        on it (her look), her mood's news (until she has replied) and how her classmates seem today; nothing
        for a routine run, or a person she has nothing on."""
        persona, trigger = context.persona, context.trigger
        if trigger.origin != "person" or not book.keeps(persona.name) or not conversation(context.engine, settings):
            return ""
        own = settings.of(persona.name)
        subject = book.subject(context.address.interface, trigger.sender.id)
        person = called(book, persona.name, subject, context.owner, trigger.sender)
        turn = guts.begin(context, subject) if guts is not None and own.gut and not impulse(trigger) else None
        memory = book.open(persona.name)
        started_over(memory, subject, context)

        async def with_gut(kept: str) -> str:
            """What she keeps of them, and the line from her gut, which reads it first."""
            if turn is None:
                return kept
            relationship = memory.relations.get(subject) if memory is not None else None
            exchanges = memory.episodes.count(subject) if memory is not None else 0
            line = await turn.feel(memory.surface.slice(subject) if memory is not None else [], kept,
                                   relationship.closeness if relationship else 0.0, exchanges)
            return "\n\n".join(part for part in (kept, line) if part)

        if memory is None:  # (nothing kept of anyone yet)
            return await with_gut(no_notes(person, own.language) if own.learn and own.notes else "")
        who = "\n".join(line for line in (memory.relations.line(subject, person),
                                          memory.aliases.line(subject, person)) if line)
        query = impulse(trigger) or trigger.text  # (speaking up, her notes for what moves her)
        alone = direct(context)
        notes, said = await asyncio.gather(  # (each waits on the same query's embedding)
            memory.memory.acontext(subject, query, user_name=person) if own.notes else _nothing(""),
            memory.alook(subject, query, user_name=person, budget=own.said, search=own.search, own=alone,
                         found=mneme_llm.SEARCHED if alone else 0) if own.said else _nothing(""))
        notes = (notes or no_notes(person, own.language)) if own.notes else ""
        # Her mood's news is told once: marked by the watcher once she has replied, so a step asked twice (or a run
        # replayed) shows it each time; without the watcher, at once.
        news = (memory.mood.news(subject, mark=not own.learn) or "") if own.mood else ""
        others = classmates_line(book, persona.name, subject, own.language) if own.classmates else ""
        return await with_gut("\n\n".join(part for part in (who, notes, said, news, others) if part))
    return text


def direct(context) -> bool:
    """A chat with her alone, whoever asks (a `PartContext`, an `Exchange`): a web page's group chat is direct too."""
    return context.trigger.is_direct and len(context.personas) == 1


def started_over(memory, subject: str, context) -> None:
    """Her copy of the conversation starts over with a chat with her alone (a `/new`). A group's does not touch it."""
    if memory is not None and direct(context) and context.since > memory.surface.began(subject):
        memory.surface.clear(subject)


def make_context(book: Book, settings: Settings):
    def context(part) -> Context | None:
        """Her surface, when she is talking with one person: what stands for what she let go, and the newest of what
        she keeps of them, whichever chat it was said in. So a new chat starts where the last one stopped, and the engine
        reads only what came after it. A group is the engine's own."""
        persona, trigger = part.persona, part.trigger
        own = settings.of(persona.name)
        if not (direct(part) and trigger.origin == "person" and own.surface and own.learn and own.episodes
                and book.keeps(persona.name) and conversation(part.engine, settings)):
            return None
        memory = book.open(persona.name)
        if memory is None:
            return None
        subject = book.subject(part.address.interface, trigger.sender.id)
        started_over(memory, subject, part)
        view = memory.surface.read(subject, user_name=called(book, persona.name, subject, part.owner, trigger.sender),
                                   here=where(part.address))
        return Context(tuple(view.messages), view.upto) if view.messages else None
    return context


def writer(models, profile: str | None):
    """mneme-llm's own calls (judging the mood, writing notes, her impression), on her model or `writer_profile`."""
    async def complete(system: str, user: str) -> str:
        result = await models.generate(ModelRequest(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], profile=profile,
            effort="none", max_tokens=1500, timeout_s=60.0))  # short judgments: thinking cost several times the reply
        return result.text
    return complete


def first_role(memory, subject: str, own: Settings, owner: bool) -> None:
    """Who someone new is to her: the bot's owner her creator (`owner_role`), anyone else an acquaintance
    (`met_role`); your `roles:` say more. An owner's second account, not joined to the first, is no second creator."""
    for role in ([own.owner_role] if owner else []) + [own.met_role]:
        try:
            if role:
                memory.relate(subject, role)
                return
        except ValueError:  # (there is one creator)
            continue


def their_words(exchange, history, after: float) -> list[str]:
    """What the sender said here since `after`, up to her message: the answer to a question, a message that came while
    she worked, one whose run failed. Their `$commands` and what she said on her own stay out of it."""
    trigger = exchange.trigger
    return [item.text for item in history.recent(REACH)
            if item.direction == "in" and item.sender_id == trigger.sender.id and item.at > after
            and (item.at <= exchange.at or item.message_id == trigger.id)
            and not is_command(item.text) and not item.text.startswith(IMPULSE)][-UNANSWERED:]


def make_learner(book: Book, settings: Settings):
    async def learn(exchange, context) -> None:
        """After each of her messages: the exchange kept word for word, how it left her feeling and what is worth
        keeping (one decision call, and a note writer only when something is), a day of contact for her closeness,
        and once a day her impression. An exchange is what the person said since her last one here (`their_words`), so
        none of it is lost and a run posting three messages keeps it once; a message that answers nothing new is kept
        as hers alone. The exchange and the notes from a group chat go to her classmates there too (`hear`, `share`). A
        message she started herself (speaking up) moves her mood only: notes and what was said come from what people
        tell her."""
        persona, trigger = exchange.persona, exchange.trigger
        if trigger.origin != "person" or not conversation(exchange.engine, settings) or not book.keeps(persona.name):
            return
        own = settings.of(persona.name)
        if not own.learn:
            return
        memory = book.open(persona.name, create=True)
        subject = book.subject(exchange.address.interface, trigger.sender.id)
        person = called(book, persona.name, subject, exchange.owner, trigger.sender)
        motive = impulse(trigger)
        if not motive and memory.relations.get(subject) is None:
            first_role(memory, subject, own, exchange.owner)
        complete = writer(context.models, own.writer_profile)
        memory.mood.news(subject, mark=True)  # she has replied: what moved her before was told
        keep = own.episodes and not motive
        place = {"conversation": where(exchange.address), "at": exchange.at}
        hers = (persona.display_name, exchange.text)
        if motive:
            said = [(f"({persona.display_name}'s own thought)", motive), hers]
            if own.episodes:  # (without it, what they answer next answers nothing she reads)
                memory.episodes.keep(subject, [("", impulse_line(motive)), hers], **place)
        else:
            words = [trigger.text]
            if keep:
                last = memory.surface.read(subject, here=where(exchange.address)).upto
                words = their_words(exchange, context.history, max(last, exchange.since))
            said = [*((person, word) for word in words), hers]
        if (own.mood or own.notes) and (motive or words):
            seen = await memory.aobserve(subject, said, source="speak-up" if motive else "user", user_name=person,
                                         complete=complete, mood=own.mood, capture=own.notes, keep=keep, **place)
            if seen.error:
                context.log("notes_not_written", persona=persona.name, error=seen.error)
            if seen.notes:
                share(book, settings, exchange, subject, seen.notes, context.facts)
        elif not motive:
            memory.relations.seen(subject)
            if keep:
                await memory.episodes.akeep(subject, said, **place)
                memory.surface.noticed(subject, said)
        if keep:
            await hear(book, settings, exchange, subject, said)
            if own.surface:
                await memory.surface.alet_go(subject, user_name=person, complete=complete)
        if own.notes and not motive:
            updated = memory.memory.profile_updated_at(subject)
            if (updated is None or time.time() - updated >= DAY) and \
                    len(memory.memory.notes(subject)) >= own.reflect_after:
                await memory.areflect(subject, user_name=person, complete=complete)
        book.publish(context.facts, persona.name, subject)
    return learn


def make_alias(book: Book, facts):
    async def alias(arguments, context) -> ToolResult:
        subject = book.subject(context.address.interface, context.sender.id)
        text = str(arguments.get("text") or "").strip()
        if not text:
            names = {persona: memory.aliases.get(subject) for persona in book.known()
                     if (memory := book.open(persona)) is not None}
            lines = [f"{book.shown(persona)}: {name}" for persona, name in names.items() if name]
            return ToolResult.ok("\n".join(["What you call them:", *lines]) if lines else
                                 "You have not named anyone yet. `$alias <student> <name>` gives one a name of yours.")
        who, _, name = text.partition(" ")
        persona = book.find(who, subject)
        if persona is None:
            shown = ", ".join(book.shown(persona) for persona in book.known()) or "nobody yet"
            return ToolResult.fail(f"No student called {who!r} here (known: {shown}).", "unknown_student")
        shown, name = book.shown(persona), name.strip()
        memory = book.open(persona, create=True)
        if not name:
            present = memory.aliases.get(subject)
            return ToolResult.ok(f"You call {shown} {present}." if present else f"You have no name for {shown} yet.")
        if name.casefold() in RESET:
            memory.alias(subject, None)
            book.publish(facts, persona, subject)
            return ToolResult.ok(f"{shown} is {shown} to you again.")
        try:
            stored = memory.alias(subject, name)
        except ValueError as error:
            return ToolResult.fail(str(error), "invalid_alias")
        book.publish(facts, persona, subject)
        return ToolResult.ok(f"You call {shown} {stored} now; she will know.", data={"persona": persona, "alias": stored})
    return alias


def make_recall(book: Book, settings: Settings, tool: str):
    """Her `search` or `read` through what was said before with the person who wrote, as mneme-llm's tools do it."""
    async def recall(arguments, context) -> ToolResult:
        persona = context.persona
        if not persona or not book.keeps(persona) or not settings.of(persona).search:
            return ToolResult.fail("Only a student's own turn can look through her memory.", "not_a_student")
        box = book.toolbox(persona, context.run_id)
        if box is None:
            return ToolResult.ok("Nothing said before is kept yet.")
        subject = book.subject(context.address.interface, context.sender.id)
        return ToolResult.ok(await box.acall(tool, dict(arguments), subject=subject))
    return recall


def publish_person(book: Book, facts, subject: str) -> None:
    """Every student's facts for this person, on each of their accounts (after a name or a link changed)."""
    for persona in book.known():
        book.publish(facts, persona, subject)


def make_callme(book: Book, facts):
    async def callme(arguments, context) -> ToolResult:
        """`$callme` shows it, `$callme <name>` asks every student, `$callme <student> <name>` one of them, and
        `reset` (for all or for her) takes the name back."""
        subject = book.subject(context.address.interface, context.sender.id)
        text = " ".join(str(arguments.get("text") or "").split())
        if not text:
            owner = context.access == "creator"
            lines = [f"{book.shown(persona)}: {book.calling(persona, subject, owner)['name'] or context.sender.name}"
                     for persona in book.known()]
            return ToolResult.ok("\n".join(["What the students call you:", *lines]) if lines else "No students yet.")
        who, _, rest = text.partition(" ")
        persona = book.find(who, subject) if rest else None
        name = rest if persona else text
        shown = book.shown(persona) if persona else "every student"
        if name.casefold() in RESET:
            book.set_call(subject, persona or "*", None)
            publish_person(book, facts, subject)
            return ToolResult.ok(f"Your name for {shown} is back to the usual." if persona
                                 else "The students call you as before.")
        if len(name) > NAME_MAX or not re.search(r"\w", name):
            return ToolResult.fail(f"A name of 1 to {NAME_MAX} characters, please.", "invalid_name")
        book.set_call(subject, persona or "*", name)
        publish_person(book, facts, subject)
        return ToolResult.ok(f"{shown[0].upper()}{shown[1:]} will call you {name}." if persona
                             else f"The students will call you {name}.",
                             data={"persona": persona, "name": name})
    return callme


def make_link(book: Book, facts):
    async def link(arguments, context) -> ToolResult:
        """`$link` gives a code (and lists your accounts); `$link <code>`, sent from another account of yours within
        ten minutes, makes the two one person to every student."""
        subject = book.subject(context.address.interface, context.sender.id)
        text = str(arguments.get("text") or "").strip()
        if not text:
            code = book.code_for(subject)
            accounts = book.accounts.get(book.person(subject), [subject])
            return ToolResult.ok(f"Your accounts: {', '.join(accounts)}. To add one, send `$link {code}` from it "
                                 f"(Discord, WeChat, another page) within ten minutes.", data={"code": code,
                                                                                        "accounts": accounts})
        person = book.redeem(text)
        if person is None:
            return ToolResult.fail("That code is wrong or too old: ask for a new one with `$link`.", "invalid_code")
        if book.person(subject) == person:
            return ToolResult.ok("This account is already yours there.")
        if not book.join(subject, person):
            return ToolResult.fail(f"{subject} belongs to someone already (`people:` in the students' settings says "
                                   "so, or other accounts are linked to it).", "taken")
        book.save()
        publish_person(book, facts, subject)
        return ToolResult.ok(f"Linked: {subject} and {person} are one person to every student now.",
                             data={"person": person, "account": subject})
    return link


def make_bond(book: Book):
    async def bond(arguments, context) -> ToolResult:
        subject = book.subject(context.address.interface, context.sender.id)
        lines = []
        for persona in book.known():
            stand = book.stand(persona, subject)
            relationship, alias = stand["bond"], stand["alias"]
            line = (f"{relationship['role']}, closeness {relationship['closeness']}/100" if relationship
                    else "no role yet")
            if stand["mood"]:
                line += f", mood {stand['mood']['value']}/100 ({stand['mood']['face']})"
            lines.append(f"{book.shown(persona)}: {line}" + (f"; you call her {alias}" if alias else ""))
        return ToolResult.ok("\n".join(lines) or "No students yet.")
    return bond


def creator_of(memory, own: Settings) -> str | None:
    """Her creator's subject (`owner_role`), once the bot's owner has talked with her and nothing gave them another."""
    for item in memory.relations.all():
        if item.role == own.owner_role:
            return item.subject
    return None


def card_holder(memory, own: Settings, asking: str | None = None) -> str | None:
    """Whose Character Card is hers: the one that is on (only the bot's owner can turn one on, and one at a time: from
    any of their accounts), else the one asking, else her creator's."""
    on = [subject for subject in memory.surface.subjects() if (card := memory.surface.card(subject)) and card.on]
    if on:
        creator = creator_of(memory, own)
        return creator if creator in on else max(on, key=lambda subject: memory.surface.card(subject).at)
    return asking or creator_of(memory, own)


def make_card_part(book: Book, settings: Settings):
    def text(context) -> str:
        """Her Character Card, once it is on: who she is, in her creator's words, with everyone she talks with. In the
        system prompt, which every turn carries and nothing compacts."""
        persona = context.persona.name
        memory = book.open(persona) if book.keeps(persona) else None
        holder = card_holder(memory, settings.of(persona)) if memory is not None else None
        card = memory.surface.card(holder) if holder else None
        return card.text if card is not None and card.on else ""
    return text


def make_card(book: Book, settings: Settings):
    def shown(persona: str, subject: str) -> str:
        memory, name = book.open(persona), book.shown(persona)
        holder = card_holder(memory, settings.of(persona), subject) if memory is not None else None
        card = memory.surface.card(holder) if holder else None
        if card is None:
            return f"{name}: no Character Card yet"
        return (f"{name}: {card.text}\n  ({'you set this' if card.by_command else 'the first thing you said'}; "
                f"{'in her system prompt, every turn' if card.on else 'only kept'})")

    def turn_on(memory, holder: str, on: bool) -> bool:
        """Hers on or off; on, it is the only one."""
        if not memory.surface.card_on(holder, on):
            return False
        for other in memory.surface.subjects() if on else ():
            if other != holder and (card := memory.surface.card(other)) and card.on:
                memory.surface.card_on(other, False)
        return True

    async def card(arguments, context) -> ToolResult:
        """`$card` shows each student's Character Card, `$card <text>` sets it for every student, `$card on` puts it in
        her system prompt, with everyone she talks with, `$card off` only keeps it, and `$card clear` takes it away. A
        student first (`$card <student> ...`) is her alone. Only the bot's owner can: it is who she is."""
        subject = book.subject(context.address.interface, context.sender.id)
        text = str(arguments.get("text") or "").strip()
        word, _, rest = text.partition(" ")
        persona = book.find(word, subject) if word else None
        if persona:
            text = rest.strip()
        personas = [persona] if persona else book.known()
        if not personas:
            return ToolResult.ok("No students yet.")
        if not text:
            return ToolResult.ok("\n".join(shown(item, subject) for item in personas))
        shown_as, word = book.shown(persona) if persona else "every student", text.casefold()
        holder = lambda memory, item: card_holder(memory, settings.of(item), subject)  # noqa: E731
        if word in ("on", "off", "clear"):
            kept = [(item, book.open(item)) for item in personas if book.has(item)]  # (asking makes no file)
            if word == "clear":
                taken = [memory.surface.drop_card(holder(memory, item)) for item, memory in kept]
                return ToolResult.ok(f"Taken away, for {shown_as}." if any(taken) else f"Nothing is kept, for {shown_as}.")
            if not any([turn_on(memory, holder(memory, item), word == "on") for item, memory in kept]):
                return ToolResult.fail("There is no Character Card yet: set one with `$card <text>`.", "no_card")
            return ToolResult.ok(f"It is in her system prompt from now on, for {shown_as}." if word == "on"
                                 else f"It is only kept now, for {shown_as}.")
        for item in personas:
            memory = book.open(item, create=True)
            memory.surface.set_card(holder(memory, item), text)
        return ToolResult.ok(f"Kept, for {shown_as}. `$card on` puts it in her system prompt.")
    return card


def make_new(book: Book, settings: Settings, guts: "Guts | None", facts):
    async def new(arguments, context) -> ToolResult:
        """`$new deep <student>` clears what she remembers of everyone, for good; `$new gut <student>` clears what people
        taught her gut as well, and she is as she was born. `everyone` in place of a student is every student. Naming
        who is the safeguard: there is no default. `/new` is the everyday one, which clears the context only."""
        words = str(arguments.get("text") or "").split()
        if len(words) != 2 or words[0] not in DEEPER:
            return ToolResult.fail("Use `$new deep <student>` or `$new gut <student>`, or `everyone` for every student. "
                                   "`/new` clears the context only.", "invalid_new")
        persona = None if words[1] == EVERYONE else book.find(words[1], book.subject(context.address.interface,
                                                                                     context.sender.id))
        if persona is None and words[1] != EVERYONE:
            return ToolResult.fail(f"No student called {words[1]!r} here. Name one, or say `everyone`.", "unknown_student")
        kept, lessons = 0, 0
        for name in [persona] if persona else book.known():
            memory = book.open(name)
            if memory is not None:
                for someone in memory.everyone():
                    kept += memory.wipe(someone)
                    book.publish(facts, name, someone)  # (what she had coming with them is gone from the pages too)
            context.start_over(name, everywhere=True)  # (her context goes with it, in every chat)
            if words[0] == "gut" and guts is not None and settings.of(name).gut:
                lessons += await asyncio.to_thread((await guts.woken(name)).wipe)
        shown = book.shown(persona) if persona else "Every student"
        told = f"{shown}: {kept} exchanges gone for good, with the notes"
        return ToolResult.ok(told + (f", and {lessons} lessons of the gut." if words[0] == "gut" else "."))
    return new


def make_gut(book: Book, settings: Settings, guts: Guts):
    async def show(arguments, context) -> ToolResult:
        """`$gut`: where each student's gut stands; nothing of what she was told is shown to anyone but the owner."""
        lines, owner = [], context.access == "creator"
        for persona in settings.personas:
            if not settings.of(persona).gut:
                continue
            found = (await guts.woken(persona)).report()
            lines.append(f"{book.shown(persona)}: {found['lessons']} lessons, {round(found['grown'] * 100)}% grown up "
                         f"(tau {found['tau']:g}), {len(found['people'])} people, last balance {found.get('share', '?')}")
            if owner:
                lines.append(f"  SAN {found['SAN']:+.2f}, self-esteem {found['self-esteem']:+.2f}, sensitivity "
                             f"{found['sensitivity']:+g}")
            if owner and found["sides"]:
                lines += [f"  side {name} ({found['weights'][name]}): {what}" for name, what in found["sides"].items()]
                lines.append(f"  she is in {', '.join(found['held'])} for {found['days']} more days at least")
            if owner and found["noted"]:
                lines.append("  noted: " + ", ".join(f"{name} {value}" for name, value in found["noted"].items())
                             + f" (a side grows at {GROWS:g})")
            if owner and found.get("told"):
                lines.append(f"  told: {found['told']}")
            if owner and found.get("note"):
                lines.append(f"  her note: {found['note']}")
        return ToolResult.ok("\n".join(lines) or "No student has a gut yet.")
    return show


def make_views(book: Book, guts: Guts, felt: tuple[str, ...]) -> list[View]:
    """Her gut for her page, the owner's alone: `students.gut` (her settings, bars, people and sides) and
    `students.starmap` (her heart as a star map), worked out when the page asks (contracts.View)."""
    from . import panel, starmap

    async def gut(persona: str, person: tuple[str, str]) -> dict:
        found, memory = await guts.woken(persona), book.open(persona)
        you = book.subject(*person)
        you = book.person_of.get(you, you)

        def made() -> dict:
            names = {subject: book.name_of(subject) for subject in found.net.people} if found is not None else {}
            return panel.view(found, you, memory, {subject: name for subject, name in names.items() if name})
        return {"student": persona, "display": book.shown(persona), **await asyncio.to_thread(made)}

    async def stars(persona: str, person: tuple[str, str]) -> dict:
        found = await guts.woken(persona)
        return {"stamp": panel.stamp(found), **await asyncio.to_thread(starmap.starmap, found)}
    return [View("gut", gut, "Her gut: settings, bars lately against usual, the people she knows, her sides",
                 personas=felt, timeout_s=30),
            View("starmap", stars, "Her heart as a star map, and the people she knows", personas=felt, timeout_s=60)]


def make_tune(book: Book, settings: Settings, guts: Guts):
    async def tune(arguments, context) -> ToolResult:
        """`$tune <student> <change>`: her gut by hand, a change as JSON (extensions/students/panel.py), checked whole
        before any of it lands; the answer's data is her gut as her page shows it."""
        from . import panel
        who, _, given = str(arguments.get("text") or "").strip().partition(" ")
        persona = book.find(who, book.subject(context.address.interface, context.sender.id)) if who else None
        if persona is None or not settings.of(persona).gut:
            return ToolResult.fail("Use `$tune <student> <change>`, the change as JSON (tau, sensitivity, age, locked, "
                                   "tune, people, sides, side).", "invalid_tune")
        try:
            asked = json.loads(given)
        except ValueError:
            return ToolResult.fail("The change is JSON: {\"tune\": [{\"end\": \"sweet\", \"nature\": 2}]}, say.",
                                   "invalid_tune")
        gut, memory = await guts.woken(persona), book.open(persona)
        try:
            await asyncio.to_thread(panel.change, gut, asked, memory)
        except ValueError as error:
            return ToolResult.fail(f"Not changed: {error}.", "invalid_tune")
        subject = book.subject(context.address.interface, context.sender.id)
        shown = await asyncio.to_thread(panel.view, gut, book.person_of.get(subject, subject), memory)
        return ToolResult.ok(f"{book.shown(persona)}'s gut: changed.", data={"gut": shown})
    return tune


def weight_of(text: str) -> float | None:
    """A weight for `$side`: a number above nothing, or None for a sentence."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0 < value < 1000 else None


def make_side(book: Book, settings: Settings, guts: Guts):
    async def side(arguments, context) -> ToolResult:
        """`$side <student> <side> <sentence>` writes a side's sentence, a better one than her model's or a new side;
        `$side <student> <side> <number>` sets how much of her it is; `$side <student> <side> off` takes one away."""
        words = str(arguments.get("text") or "").split(None, 2)
        persona = book.find(words[0], book.subject(context.address.interface, context.sender.id)) if words else None
        if len(words) < 3 or persona is None or not settings.of(persona).gut:
            return ToolResult.fail("Use `$side <student> <side> <sentence>`, `$side <student> <side> <number>`, or "
                                   "`$side <student> <side> off`.", "invalid_side")
        gut = await guts.woken(persona)
        if words[2] == "off":
            return ToolResult.ok(f"Gone: {words[1]}." if gut.drop_side(words[1]) else f"She has no side {words[1]}.")
        weight = weight_of(words[2])
        if weight is not None:
            if words[1] not in gut.grown:
                return ToolResult.fail(f"She has no side {words[1]}.", "invalid_side")
            gut.write_side(words[1], gut.grown[words[1]], weight)
            return ToolResult.ok(f"{book.shown(persona)}'s {words[1]} side: {weight:g}")
        try:
            gut.write_side(words[1], words[2])
        except ValueError as error:
            return ToolResult.fail(str(error), "invalid_side")
        return ToolResult.ok(f"{book.shown(persona)}'s {words[1]} side: {words[2]}")
    return side


def contributions(context, students: dict[str, dict]) -> dict:
    """The memory's prompt part, watcher, commands and facts, for these students (persona → display name and other
    names), or those of them `personas:` names."""
    config = dict(context.config)
    # Each student's own memory settings (her student.yml `memory:`), under this module's `students: <name>:`.
    given = dict(config.get("students") or {})
    config["students"] = {name: {**dict((students.get(name) or {}).get("memory") or {}), **dict(given.get(name) or {})}
                          for name in [*given, *(name for name in students if (students[name] or {}).get("memory"))]}
    settings = Settings(config, Path(context.data_dir))
    keep = tuple(name for name in settings.personas or students if name in students)
    settings.personas = keep
    book = Book(context.data_dir, personas=keep, names=students,
                platforms={**context.platforms, **dict(config.get("platforms") or {})}, roles=config.get("roles"),
                people=config.get("people"), settings=settings)
    facts = context.facts
    book.publish_all(facts)
    learns = settings.learn or any(flag(own.get("learn"), False) for own in settings.students.values())
    searching = tuple(name for name in keep if settings.of(name).search)
    spec = {item["name"]: item for item in SPECS}
    felt = tuple(name for name in keep if settings.of(name).gut)
    guts = Guts(Path(context.data_dir) / "gut", {name: Path(students[name]["folder"]) / STARTER for name in felt
                                                 if students[name].get("folder")}) if felt else None
    return {
        "prompt_parts": [PromptPart("card", make_card_part(book, settings), place="stable", order=110, personas=keep),
                         PromptPart("memory", make_part(book, settings, guts), place="turn", order=50, personas=keep),
                         PromptPart("surface", make_context(book, settings), place="context", personas=keep)],
        "watchers": [*([Watcher("memory", make_learner(book, settings), personas=keep, timeout_s=180)] if learns else []),
                     *([Watcher("gut", guts.learn, personas=felt, timeout_s=120)] if felt else [])],
        "capabilities": [
            *([Capability("students.gut", "Where each student's gut stands.", make_gut(book, settings, guts),
                          risk=Risk.READ, internal=True, command="gut"),
               Capability("students.side", "Write a side of a student's, or take one away.",
                          make_side(book, settings, guts),
                          {"text": {"type": "string", "description": "<student> <side> <sentence>, <student> <side> <number>, or <student> <side> off"}},
                          risk=Risk.WRITE, access="creator", internal=True, command="side",
                          command_argument="text")] if felt else []),
            *([Capability("students.tune", "Change a student's gut by hand: her settings, feelings, people and sides.",
                          make_tune(book, settings, guts),
                          {"text": {"type": "string", "description": "<student> <change as JSON>"}},
                          risk=Risk.WRITE, access="creator", internal=True, command="tune",
                          command_argument="text")] if felt else []),
            Capability("students.card", "Show or set the students' Character Card: who she is, in her system prompt.",
                       make_card(book, settings),
                       {"text": {"type": "string", "description": "<text>, on, off, clear, a student first, or nothing"}},
                       risk=Risk.WRITE, access="creator", internal=True, command="card", command_argument="text"),
            Capability("students.new", "Start over deeper than /new, for one student or everyone: what they remember, "
                       "for good.", make_new(book, settings, guts, facts),
                       {"text": {"type": "string", "description": "deep or gut, then a student or everyone"}},
                       risk=Risk.CRITICAL, access="creator", internal=True, command_argument="text",
                       command=Command("new", "Start over deeper than /new, for one student or everyone",
                                       (Option("text", "deep or gut, then a student or everyone"),), menu=False)),
            Capability("students.alias", "Show or set what you call a student.", make_alias(book, facts),
                       {"text": {"type": "string", "description": "<student> <name>, <student> reset, or nothing"}},
                       risk=Risk.WRITE, internal=True, command="alias", command_argument="text"),
            Capability("students.bond", "Where each student stands with you.", make_bond(book), risk=Risk.READ,
                       internal=True, command="bond"),
            Capability("students.callme", "Show or set what the students call you.", make_callme(book, facts),
                       {"text": {"type": "string", "description": "<name>, <student> <name>, reset, or nothing"}},
                       risk=Risk.WRITE, internal=True, command="callme", command_argument="text"),
            Capability("students.link", "Join another account of yours, with a code.", make_link(book, facts),
                       {"text": {"type": "string", "description": "a code from `$link`, or nothing for a new one"}},
                       risk=Risk.WRITE, internal=True, command="link", command_argument="text"),
            # Hers alone (offered to her turns only), about the person who wrote, never anyone else.
            *([Capability("students.search_memory", spec["search"]["description"],
                          make_recall(book, settings, "search"), spec["search"]["parameters"]["properties"],
                          required=("query",), risk=Risk.READ, personas=searching, timeout_s=60),
               Capability("students.read_memory", spec["read"]["description"], make_recall(book, settings, "read"),
                          spec["read"]["parameters"]["properties"], required=("id",), risk=Risk.READ,
                          personas=searching, timeout_s=60)] if searching else []),
        ],
        # Each changes only what is yours (your name for her, her name for you, your own accounts: a link needs a
        # code from the account it joins), and only you can type them (models are not offered them).
        "permissions": {"*": {"rules": {"students.alias": "auto", "students.callme": "auto", "students.link": "auto",
                                        "students.card": "auto", "students.tune": "auto"}}},
        # Her gut for her page (the owner's alone): what it shows, worked out when asked.
        "views": make_views(book, guts, felt) if felt else [],
    }

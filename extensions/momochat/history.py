"""What a speaker reads of the conversation: the thread since `/new`, its latest messages word for word (the window),
the older ones as the conversation's rolling summary, and the images shared shortly before.

`$commands` and their answers are not part of it (`$model`'s lists, `$help`): they are for the person who typed them.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
import re
import time

from contracts import FileRef, ModelError, ModelRequest, Session

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")
NEW_THREAD = {"/new", "/reset", "/clear"}
REACH = 200  # messages of the chat a thread is read from
SURFACE_REACH = 30000  # and with `surface` on
# The surface, as mneme-llm counts it: what the last SURFACE_DAYS talking days hold, never less than SURFACE_FLOOR
# tokens, let go at twice that, with SURFACE_CAP the top whatever the rest says, or 80% of the model's window.
SURFACE_DAYS, SURFACE_FLOOR, SURFACE_CAP, SURFACE_WINDOW = 30, 70_000, 504_000, 1_048_576
DAY_STARTS = 4  # a talking day turns at 4 in the morning
WIDE = re.compile("[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]")
# How an interface marks a message it sent on a persona's own impulse (with `extra.speak_up`, Whale-chan's bot
# speaking up): in history it is her impulse, not something the person said.
IMPULSE = "⟨speak-up⟩ "
COMPACT_RETRY_S = 15 * 60  # after a failed summary call, wait this long before trying again
COMPACT = """You keep the running summary of a group conversation, so its participants can follow it once the messages themselves are out of view. Rewrite the summary to cover the new messages too: who said what that matters, decisions, plans, promises, open questions, facts people shared about themselves, and the mood. Drop small talk and anything already settled. Plain text, in the conversation's main language, at most 300 words."""


def is_image(file: FileRef) -> bool:
    return (file.mime or "").startswith("image/") or file.path.lower().endswith(IMAGE_SUFFIXES)


def add_images(state: dict, files) -> None:
    """Remember image attachments of the run's messages and tool results (latest 6) so every step can see them."""
    for file in files or ():
        item = dataclasses.asdict(file) if dataclasses.is_dataclass(file) else dict(file)
        if (item.get("mime") or "").startswith("image/") or item["path"].lower().endswith(IMAGE_SUFFIXES):
            state["images"] = [*state.get("images", []), item][-6:]


def images(state: dict) -> tuple[FileRef, ...]:
    return tuple(FileRef(**item) for item in state.get("images", []))


def recent_images(items, now: float, window_s: float, limit: int = 4) -> list[FileRef]:
    """Images people sent shortly before this request (WeChat sends a picture and its question separately), newest
    last."""
    found: list[FileRef] = []
    for item in sorted(items, key=lambda entry: entry.at, reverse=True):
        if now - item.at > window_s or len(found) >= limit:
            break
        if item.direction == "in":
            found.extend(file for file in reversed(item.files) if is_image(file))
    return list(reversed(found[:limit]))


def combine_images(*groups) -> tuple[FileRef, ...]:
    seen, result = set(), []
    for file in (file for group in groups for file in group):
        if file.path not in seen:
            seen.add(file.path)
            result.append(file)
    return tuple(result[-6:])


def new_thread(text: str) -> list[str] | None:
    """`/new` with at most one word after it, as that word (or nothing), or None for anything else."""
    words = text.strip().lower().split()
    return words[1:] if 1 <= len(words) <= 2 and words[0] in NEW_THREAD else None


def tokens(item) -> float:
    """About what a message costs a model (within 3% of DeepSeek's count on two months of chat)."""
    wide = len(WIDE.findall(item.text))
    return wide * .85 + (len(item.text) - wide) * .3 + 1.2


def talking_day(at: float) -> int:
    return (dt.datetime.fromtimestamp(at).astimezone() - dt.timedelta(hours=DAY_STARTS)).toordinal()


def surface_bounds(items, window: int = SURFACE_WINDOW) -> tuple[int, int]:
    """What the surface keeps and what it may reach, given what is in it and what the model reads at most."""
    days: dict[int, int] = {}  # (a quarter of an hour's day: a day turns on one)
    for item in items:
        days.setdefault(int(item.at // 900), 0)
    days = {quarter: talking_day(quarter * 900.0) for quarter in days}
    edge = (sorted(set(days.values()))[-SURFACE_DAYS:] or [0])[0]
    recent = sum(tokens(item) for item in items if days[int(item.at // 900)] >= edge)
    top = min(SURFACE_CAP, window * 4 // 5)
    keep = min(max(SURFACE_FLOOR, int(recent)), top * 2 // 3)
    return keep, min(2 * keep, top)


def is_command(text: str) -> bool:
    """A `$command`, as the core tells them apart (`$` and a letter)."""
    text = text.strip()
    return len(text) > 1 and text[0] == "$" and text[1].isalpha()


def line(item, named: bool, shown: set[str]) -> str:
    """One readable entry from someone else: time, speaker (in a group), text, what it replied to, attachments."""
    if item.direction == "in" and item.text.startswith(IMPULSE):
        return f"(You messaged them on your own then: {item.text[len(IMPULSE):].strip()})"
    when = dt.datetime.fromtimestamp(item.at).astimezone().strftime("%m-%d %H:%M")
    speaker = (item.sender_name or ("assistant" if item.direction == "out" else item.sender_id))
    text = f"[{when}] {speaker + ': ' if named or item.direction == 'out' else ''}{item.text}"
    if item.quoted_text:
        text += f"\n(replying to: {item.quoted_text[:300]})"
    for file in item.files:
        text += f"\n[{'image' if is_image(file) else 'file'} {file.name or 'attachment'}"
        text += ", shown to you with this request]" if file.path in shown else "]"
    return text


def number(value, default: float, low: float, high: float, kind=int):
    """A numeric setting clamped to [low, high]; a value that is not a number (or not finite) is the default."""
    if value is None or isinstance(value, bool):
        return kind(default)
    try:
        result = kind(value) if not isinstance(value, str) else kind(float(value.strip()))
    except (TypeError, ValueError, OverflowError):
        return kind(default)
    if isinstance(result, float) and not math.isfinite(result):
        return kind(default)
    return max(kind(low), min(result, kind(high)))


def flag(value, default: bool) -> bool:
    """An on/off setting as people write it in YAML or JSON: true/false, yes/no, on/off, 1/0. Anything else (or
    nothing) is the default, so `"false"` is never mistaken for on."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower() if isinstance(value, str) else ""
    return True if text in ("true", "yes", "on", "1") else False if text in ("false", "no", "off", "0") else default


class Reading:
    """The conversation as one run's speakers read it (the engine's settings under the assignment's options), or as
    `persona` does, whose own `/new` the others are not held to."""

    def __init__(self, session: Session, settings, persona: str = ""):
        self.session, self.settings, self.persona = session, settings, persona
        options = session.options
        self.surface = flag(options.get("surface"), settings.surface)
        self.window_tokens = number(options.get("history_window"), settings.history_window, 1000, 100_000_000)
        self.limit = number(options.get("history_limit") or None, settings.history_limit, 1, 150)
        self.chars = number(options.get("history_chars"), settings.history_chars, 0, 400000)
        self.compact = flag(options.get("compact"), settings.compact)
        self.compact_every = number(options.get("compact_every"), settings.compact_every, 1, 1000)
        self.compact_profile = str(options.get("compact_profile") or settings.compact_profile)
        self.image_window = number(options.get("history_image_minutes"), 30, 0, 24 * 60, float) * 60

    # ---- the thread -------------------------------------------------------------------------------------------
    def thread_since(self) -> float:
        """When this conversation's thread began: its last `/new` (0: never). One begun for a student alone counts too
        (`/new <her>`, or her own bot's chat engine, kept in her memory then), and the last time her memory was wiped,
        wherever that was typed."""
        session = self.session
        since = float(session.store(conversation=True).get("thread_since") or 0)
        for name in [self.persona] if self.persona else [persona.name for persona in session.personas]:
            memory = session.memory(name)
            since = max(since, float(memory.get(f"thread_since:{session.address}") or 0),
                        float(memory.get("thread_since") or 0))
        return since

    def conversation(self, reach: int = REACH) -> list:
        """The thread before this request, without `$commands` and their answers. "Before" is by position: everything
        recorded ahead of the trigger, even in the same second (some platforms send whole seconds)."""
        session = self.session
        items = session.history.recent(reach)
        trigger = session.trigger.id
        cut = next((index for index in range(len(items) - 1, -1, -1)
                    if items[index].direction == "in" and items[index].message_id == trigger), None)
        if cut is not None:
            items = items[:cut]
        else:  # not recorded (or scrolled out of reach): by time
            items = [item for item in items if item.at < session.trigger.received_at]
        since = self.thread_since()
        commands = {item.message_id for item in items if item.direction == "in" and is_command(item.text)}
        items = [item for item in items if item.at > since and new_thread(item.text) is None
                 and not (item.direction == "in" and is_command(item.text))
                 and not (item.direction == "out" and item.reply_to and item.reply_to in commands)]
        if session.options.get("history_scope") == "sender" and not session.trigger.is_direct:
            # Only this member's own messages and the replies that answered them.
            sender = session.trigger.sender.id
            theirs = {item.message_id for item in items if item.direction == "in" and item.sender_id == sender}
            items = [item for item in items if (item.direction == "in" and item.sender_id == sender)
                     or (item.direction == "out" and item.reply_to in theirs)]
        return items

    def split(self) -> tuple[list, list]:
        """The thread as (older, window): the window is the last `history_limit` messages (within `history_chars`,
        newest first, when that is set), read word for word; the summary covers the older ones, so each message is in
        one or the other. A second is never split between them: the summary's `upto` is a time. With `surface`, all of
        it after the summary is the window, so that a provider's cache keeps serving it, up to its top; `fold` lets the
        older part go there."""
        if self.surface:
            return self._surface(self.conversation(SURFACE_REACH))
        items = self.conversation()
        start = max(0, len(items) - self.limit)
        if self.chars:
            used = 0
            for index in range(len(items) - 1, start - 1, -1):
                used += len(items[index].text)
                if used > self.chars and index < len(items) - 1:
                    start = index + 1
                    break
        while 0 < start < len(items) and items[start - 1].at >= items[start].at:
            start -= 1
        return items[:start], items[start:]

    def _surface(self, items: list) -> tuple[list, list]:
        summary = self.summary()
        upto = summary.upto if summary and math.isfinite(summary.upto) else 0.0
        held = next((index for index, item in enumerate(items) if item.at > upto), len(items))
        _, top = surface_bounds(items[held:], self.window_tokens)
        start, used = len(items), 0.0
        while start > held and used + tokens(items[start - 1]) <= top:
            start -= 1
            used += tokens(items[start])
        return items[:start], items[start:]

    def _leaving(self) -> list:
        """What the surface lets go now: nothing until it reaches its top, then all but what it keeps."""
        older, window = self.split()
        summary = self.summary()
        covered = summary.upto if summary and math.isfinite(summary.upto) else self.thread_since()
        fresh = [item for item in older if item.at > covered]
        keep, top = surface_bounds(window, self.window_tokens)
        left = sum(tokens(item) for item in window)
        if left < top and not fresh:
            return []
        for index, item in enumerate(window):
            if left <= keep and (not index or window[index - 1].at < item.at):
                break
            fresh.append(item)
            left -= tokens(item)
        return fresh

    def window(self) -> list:
        return self.split()[1]

    def summary(self):
        """The rolling summary, if it covers this thread (one written before the last `/new` is not read)."""
        summary = self.session.history.summary()
        if summary is None or not self.compact or summary.upto <= self.thread_since():
            return None
        return summary

    def shown_images(self, items) -> list[FileRef]:
        return recent_images(items, self.session.trigger.received_at, self.image_window)

    async def fold(self) -> None:
        """Fold messages that scrolled out of the window into the conversation's rolling summary, once enough have
        (`compact_every`), with one call to `compact_profile` (the cheap default). A failure leaves the old summary;
        the conversation goes on either way."""
        if not self.compact:
            return
        session = self.session
        store = session.store(conversation=True)
        if float(store.get("compact_retry_at", 0) or 0) > time.time():
            return  # it failed recently: not on every message (each try costs a model call)
        summary = self.summary()
        covered = summary.upto if summary and math.isfinite(summary.upto) else self.thread_since()
        if self.surface:
            fresh = self._leaving()
            if not fresh:
                return
        else:
            older, _ = self.split()
            fresh = [item for item in older if item.at > covered]
            if len(fresh) < self.compact_every:
                return
        lines = "\n".join(line(item, True, set()) for item in fresh)
        try:
            result = await session.models.generate(ModelRequest(
                [{"role": "system", "content": COMPACT},
                 {"role": "user", "content": f"Summary so far:\n{summary.text if summary else '(none yet)'}\n\n"
                                             f"New messages:\n{lines}"}],
                profile=self.compact_profile, max_tokens=2000 if self.surface else 900, effort="low"))
        except ModelError:
            store.set("compact_retry_at", time.time() + COMPACT_RETRY_S)
            return
        if result.text.strip():
            try:
                session.history.summarize(result.text.strip()[:8000], upto=fresh[-1].at)
            except ValueError:  # refused (a message recorded with a broken time, say): like a failed call
                store.set("compact_retry_at", time.time() + COMPACT_RETRY_S)

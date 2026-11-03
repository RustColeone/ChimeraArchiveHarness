"""Small things the core and every module share, each in one place."""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Callable, Mapping

NAME = re.compile(r"^[a-z][a-z0-9_]*$")  # a module's, a watcher's, a fact's or a setting's name
# Starts the text of a turn a persona started herself, so history shows it as her impulse. Only a request with
# `extra.speak_up` keeps it: the gateway takes it off anything else.
IMPULSE = "⟨speak-up⟩ "


def impulse(request) -> str:
    """Her motive when this request is a turn she started herself (`extra.speak_up`, which only an interface's own
    code sets, never a person), else ""."""
    return str(request.extra.get("speak_up") or "")


def impulse_line(motive: str) -> str:
    """How she reads, later, a turn she started herself."""
    return f"(You messaged them on your own then: {motive})"


def is_command(text: str) -> bool:
    """A `$command`, as the core tells them apart (`$` and a letter)."""
    text = text.strip()
    return len(text) > 1 and text[0] == "$" and text[1].isalpha()


def flag(value, default: bool) -> bool:
    """An on/off setting as people write it in YAML or JSON: true/false, yes/no, on/off, 1/0. Anything else (or
    nothing) is the default, so `"false"` is never mistaken for on."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = value.strip().lower() if isinstance(value, str) else ""
    return True if text in ("true", "yes", "on", "1") else False if text in ("false", "no", "off", "0") else default


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


def persona_names(value, owner: str) -> tuple[str, ...]:
    """Persona names as contracts keep them, given one name or a list; anything else is `owner`'s ValueError."""
    value = (value,) if isinstance(value, str) else value
    if not isinstance(value, (tuple, list, set, frozenset)) or not all(isinstance(name, str) and name for name in value):
        raise ValueError(f"{owner}: personas is a list of persona names")
    return tuple(value)


def local_time(at: float, shape: str = "%Y-%m-%d %H:%M") -> str:
    """A stored time for people, in local time; one an interface recorded wrongly (in milliseconds, say) is shown as
    unknown instead of failing whatever shows it."""
    try:
        return dt.datetime.fromtimestamp(at).astimezone().strftime(shape)
    except (OverflowError, OSError, ValueError, TypeError):
        return "unknown time"


def code_style(markdown: bool) -> Callable[[Any], str]:
    """How to show a command or an ID in a text: in backticks where Markdown shows."""
    return (lambda value: f"`{value}`") if markdown else str


def fact(values: Mapping[str, Any], name: str) -> Any:
    """The first fact of that name (`alias`, `bond`), whichever module published it; None when nobody did."""
    return next((value for key, value in values.items() if key.rsplit(".", 1)[-1] == name), None)


def place_key(name: Any) -> str:
    """A name as places compare them (contracts.PLACE_STATUS): lowercased, its letters and digits in any script
    ("Flash-chan" → "flashchan", "露娜" → "露娜")."""
    return re.sub(r"[\W_]", "", str(name or "").lower())[:40]


def chinese(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text or ""))


def split_text(text: str, limit: int) -> list[str]:
    """Text in chunks of at most `limit` characters, cut at a blank line, a line or a space where one is near the end."""
    chunks, remaining = [], text
    while len(remaining) > limit:
        cut = 0
        for separator in ("\n\n", "\n", " "):
            # The chunk keeps its separator, so the separator must end within the limit.
            boundary = remaining.rfind(separator, 0, limit - len(separator) + 1)
            if boundary >= limit // 2:
                cut = boundary + len(separator)
                break
        chunks.append(remaining[:cut or limit])
        remaining = remaining[cut or limit:]
    return [*chunks, remaining] if remaining or not chunks else chunks

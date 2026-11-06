"""What a student's settings page sets of the students' settings, kept in the module's data folder (settings.json) over
them: the latest word wins. A value set on the page stands until the settings it stands over say something else; then
that is the latest word, and the page's is let go. What lives in her files (her card, closeness, her memory's own
settings, her gut) the page writes there itself, and what is the app's for every student (your accounts, what you asked
to be called) goes where `$link` and `$callme` keep it: those need nothing here.

The settings a value stands over are her `student.yml` (`display_name`), the module's settings and hers under
`students:` or her `memory:` (the keys in OWN), and `roles:` (`role:<subject>`, who someone is to her).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

# The settings the page may set: her name (from the next start), the language she answers in, what she calls the owner
# and the role of people she meets, her look and her surface's size, and what she keeps.
KEYS = ("display_name", "reply_language", "call_owner", "met_role", "said", "surface_days", "surface_floor",
        "surface_cap", "surface_window", "learn", "notes", "mood", "classmates", "episodes", "surface")
ROLE = "role:"  # `role:<subject>`: who they are to her, over `roles:`


def _same(one, other) -> bool:
    return json.dumps(one, sort_keys=True, ensure_ascii=False) == json.dumps(other, sort_keys=True, ensure_ascii=False)


def known(key: str) -> bool:
    return key in KEYS or (key.startswith(ROLE) and len(key) > len(ROLE))


class Kept:
    """The page's words for every student, in `file`."""

    def __init__(self, file: Path):
        self.file = Path(file)
        try:
            read = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            read = {}  # (none yet, or unreadable: the settings alone)
        self.words: dict[str, dict[str, dict]] = {}
        for persona, items in (read.items() if isinstance(read, dict) else ()):
            if isinstance(items, dict):
                self.words[str(persona)] = {key: item for key, item in items.items()
                                            if known(key) and isinstance(item, dict) and "value" in item}

    def standing(self, persona: str, key: str, given: Any) -> bool:
        """Whether the page's word for `key` stands: the settings still say what they said when it was given."""
        item = self.words.get(persona, {}).get(key)
        return item is not None and _same(item.get("config"), given)

    def value(self, persona: str, key: str, given: Any) -> Any:
        """The page's word for `key` where it stands, else `given` (what the settings say)."""
        return self.words[persona][key]["value"] if self.standing(persona, key, given) else given

    def over(self, persona: str, given: Mapping[str, Any]) -> dict:
        """The page's standing words among `given` (key → what the settings say of it)."""
        return {key: self.words[persona][key]["value"] for key, said in given.items()
                if self.standing(persona, key, said)}

    def keys(self, persona: str) -> list[str]:
        return list(self.words.get(persona, {}))

    def set(self, persona: str, values: Mapping[str, Any], given: Mapping[str, Any]) -> None:
        """Keep `values` as the latest word, each over what `given` says the settings have now; one equal to that
        lets the page's go."""
        own = self.words.setdefault(persona, {})
        for key, value in values.items():
            if not known(key):
                raise ValueError(f"not a setting the page keeps: {key}")
            if _same(value, given.get(key)):
                own.pop(key, None)
            else:
                own[key] = {"value": value, "config": given.get(key)}
        if not own:
            self.words.pop(persona, None)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.file.with_name(f"{self.file.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(self.words, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self.file)

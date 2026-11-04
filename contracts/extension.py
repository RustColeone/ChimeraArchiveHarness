"""Extension declaration: one entry file, any of three contributions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence

from contracts.capability import Capability
from contracts.engine import Engine, Persona, PromptPart
from contracts.interface import Interface
from contracts.models import AdapterFactory
from contracts.shared import NAME
from contracts.stores import Facts
from contracts.views import View
from contracts.watchers import Watcher

PACKAGE = re.compile(r"^package:[A-Za-z0-9][A-Za-z0-9._-]*(>=[0-9][0-9A-Za-z.]*)?$")


class ExtensionContext(Protocol):
    """What an extension receives at setup."""

    name: str
    config: Mapping[str, Any]
    data_dir: Path
    facts: Facts  # what this module publishes about personas, for interfaces (any time after setup)
    present: frozenset  # which of the modules it `uses` are loaded (they were set up before it)
    prices: Any  # the core's model prices (contracts.stores.Prices)
    platforms: Mapping[str, str]  # every module's `Extension.platforms`, known before any is set up

    def log(self, event: str, **fields: Any) -> None: ...

    def personas(self) -> list[dict]:
        """the agents loaded so far (the core's and those of the modules set up before this one, so
        every module it requires or uses that is there), as `InterfacePort.personas` describes them, each with the
        `module` that added her, her `description`, `profile`, `profiles` and `models` (`default` and each tier → the
        candidates, `{provider, model}`). Called any time after setup, it lists them all."""


@dataclass(frozen=True)
class Contributions:
    """What an extension adds. Besides interfaces, engines, capabilities and personas, an extension
    may suggest defaults so it works when dropped in: model `providers` (name → settings, as in core.yml;
    configured settings win key by key) and `profiles` (name → ordered candidates, as in core.yml), and
    `assignments` and `admission` rules for its own interfaces' addresses (`<interface>:*` or
    `<interface>:<conversation>`). core.yml and runtime edits always win.

    `permissions` suggests permission defaults in the core.yml `permissions:` form
    (`{pattern: {use, tiers, rules}}`): `use` and `tiers` only for its own interfaces' addresses, `rules`
    only for its own capabilities. The module's config.yml `permissions:` overrides these, and core.yml
    overrides both, setting by setting.

    `adapters` adds provider kinds (kind → AdapterFactory) for APIs the built-in kinds do not speak; its
    providers, and core.yml's, may then use `kind: <that kind>`. A kind that already exists is refused.

    `watchers` see every persona's delivered messages, whichever engine she spoke in (see Watcher). `secrets` are file
    patterns in the module's data folder that models may never read (keys it keeps there). `views` are read-only data
    for pages, bigger than facts and never stored (see View)."""

    interfaces: Sequence[Interface] = ()
    engines: Sequence[Engine] = ()
    capabilities: Sequence[Capability] = ()
    personas: Sequence[Persona] = ()
    profiles: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    assignments: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    admission: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    permissions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    providers: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    adapters: Mapping[str, AdapterFactory] = field(default_factory=dict)
    prompt_parts: Sequence[PromptPart] = ()  # parts for every persona, or for those each part names
    watchers: Sequence[Watcher] = ()
    secrets: Sequence[str] = ()
    views: Sequence[View] = ()


@dataclass(frozen=True)
class Setting:
    """One setting a module asks for, so `python -m core setup` and `$setup` can offer it.

    `key` is the key in the module's `config.yml`. A `secret` setting (a token, an API key) is never kept
    there nor shown in chat: it goes into `.env` under `env` (the first name if several; any of them
    counts as set), and only the guided setup on the machine asks for it. `ask` puts it in the first-run
    questions. `check`, if given, tries a newly entered value (`async check(value) -> str`): it returns a
    short success note (for example the bot's name) or raises ValueError with the reason.
    """

    key: str
    description: str
    kind: str = "text"            # text, secret, number, boolean, list, path
    default: Any = None
    env: str | tuple[str, ...] = ()
    ask: bool = False
    check: Callable[[str], Awaitable[str]] | None = None

    KINDS = ("text", "secret", "number", "boolean", "list", "path")

    def __post_init__(self):
        if self.kind not in self.KINDS:
            raise ValueError(f"Setting {self.key!r}: kind must be one of {self.KINDS}")
        names = (self.env,) if isinstance(self.env, str) else tuple(self.env)
        object.__setattr__(self, "env", tuple(name for name in names if name))
        if self.kind == "secret" and not self.env:
            raise ValueError(f"Setting {self.key!r}: a secret needs `env` (the .env variable it is kept in)")
        if not NAME.match(self.key):
            raise ValueError(f"Setting keys are lowercase letters, digits or _, got {self.key!r}")


@dataclass(frozen=True)
class Extension:
    """Declared as `EXTENSION` in an extension's `extension.py`.

    `setup` receives an ExtensionContext and returns Contributions. `settings` declares what the module can be set
    up with (see Setting); it is read without running `setup`.

    `requires` and `uses` declare the other modules it builds on, by module name. Without one it
    `requires`, the module is not loaded (and says why); a Python package is `package:<name>` or
    `package:<name>>=<version>`. Without one it `uses`, it loads, minus what that module would add: its setup is
    told which are there (`ExtensionContext.present`). Every engine and persona its defaults name must belong to the
    core or to a module it declares, or it is refused.

    `platforms` names the interfaces of this module that reach another platform's people (`{"whale_chan": "discord"}`:
    one person, whichever bot they talk to). Every module is told them at setup (`ExtensionContext.platforms`), so a
    module that keeps people apart by platform needs no one's name.
    """

    name: str
    setup: Callable[[ExtensionContext], Contributions]
    description: str = ""
    settings: Sequence[Setting] = ()
    requires: Sequence[str] = ()
    uses: Sequence[str] = ()
    platforms: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not NAME.match(self.name):
            raise ValueError(f"Extension name must be lowercase letters, digits or _, got {self.name!r}")
        object.__setattr__(self, "settings", tuple(self.settings))
        object.__setattr__(self, "platforms", dict(self.platforms))
        for key in ("requires", "uses"):
            value = getattr(self, key)
            if isinstance(value, str):
                raise ValueError(f"{self.name}: `{key}` is a list of module names, not one string")
            value = tuple(value)
            for item in value:
                if not (NAME.match(item) or (key == "requires" and PACKAGE.match(item))):
                    raise ValueError(f"{self.name}: `{key}` takes module names"
                                     + (" or package:<name>" if key == "requires" else "") + f", not {item!r}")
                if item == self.name:
                    raise ValueError(f"{self.name} cannot depend on itself")
            object.__setattr__(self, key, value)
        both = set(self.requires) & set(self.uses)
        if both:
            raise ValueError(f"{self.name}: {sorted(both)} cannot be both required and used")
        keys = [setting.key for setting in self.settings]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.name}: setting keys must be unique")

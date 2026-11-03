"""Agents are described for other engines (Persona.description, Persona.profiles, ExtensionContext.personas)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from contracts import Persona
from core.app import Core
from tests.core_support import FIXTURES, FakeAdapter, make_config

# A module of the tests' own, and what it saw of the agents and its settings at setup.
MODULE = """
from contracts import Contributions, Extension, Persona
SEEN = {{}}


def setup(context):
    SEEN["agents"] = {{view["name"]: view for view in context.personas()}}
    SEEN["config"] = dict(context.config)
    SEEN["present"] = sorted(context.present)
    SEEN["context"] = context
    return Contributions({contributions})


EXTENSION = Extension({name!r}, setup{declared})
"""


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cores = []

    async def asyncTearDown(self):
        for core in self.cores:
            if core.started:
                await core.stop()
            else:
                core.tank.close()
                core.bottle.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def module(self, name, contributions="", declared="", config=None):
        folder = self.tmp / "modules" / name
        folder.mkdir(parents=True)
        (folder / "extension.py").write_text(MODULE.format(name=name, contributions=contributions, declared=declared),
                                             encoding="utf-8")
        if config:
            (folder / "config.yml").write_text(json.dumps(config), encoding="utf-8")
        return str(folder)

    async def build(self, *modules, start=False, **overrides):
        config = make_config(self.tmp, {"extensions": [str(FIXTURES / "fake"), str(FIXTURES / "probe"), *modules],
                                        **overrides})
        core = Core(config, provider_adapters={"fake": FakeAdapter()}, tick_seconds=3600)
        self.cores.append(core)
        await (core.start() if start else core.build())
        return core

    @staticmethod
    def seen(core, name):
        return next(item.module for item in core.extensions if item.extension.name == name).SEEN


class DeclarationTests(unittest.TestCase):
    def test_descriptions_and_tiers_are_checked(self):
        gpt = Persona("gpt", "GPT", "…", "gpt", description=" GPT, the\ncalm president ",
                      profiles={"own": "gpt_own", "strong": "gpt_strong"})
        self.assertEqual(gpt.description, "GPT, the calm president")
        self.assertEqual((gpt.tier("strong"), gpt.tier("own")), ("gpt_strong", "gpt_own"))
        self.assertEqual(Persona("x", "X", "…", "x", profiles={"own": "x_own"}).tier("strong"), "x_own")
        self.assertEqual(Persona("x", "X", "…", "x").tier("strong"), "x")
        with self.assertRaisesRegex(ValueError, "tier"):
            Persona("x", "X", "…", profiles={"fast": "x_fast"})


class AgentTests(Base):
    async def test_a_module_sees_the_agents_loaded_before_it_with_their_models(self):
        core = await self.build(
            self.module("students", 'personas=[Persona("gpt", "GPT", "…", "gpt", description="GPT, the president", '
                                    'profiles={"own": "gpt"})], profiles={"gpt": [{"provider": "fake", "model": "g"}]}'),
            self.module("chimera", declared=', uses=("students",)'),
            profiles={"default": [{"provider": "fake", "model": "fake-model"}],
                      "gpt": [{"provider": "fake", "model": "sol"}]})  # core.yml's wins
        agents = self.seen(core, "chimera")["agents"]
        self.assertEqual(agents["gpt"]["module"], "students")
        self.assertEqual(agents["gpt"]["description"], "GPT, the president")
        self.assertEqual(agents["gpt"]["models"]["strong"], [{"provider": "fake", "model": "sol"}])
        self.assertEqual(agents["p"]["module"], "core")  # core.yml's agent
        self.assertNotIn("chimera", self.seen(core, "students")["agents"])
        later = {view["name"] for view in self.seen(core, "students")["context"].personas()}
        self.assertEqual(later, {"p", "gpt"})  # after setup: every agent

    async def test_core_yml_defines_an_agent_with_her_models_in_one_entry(self):
        core = await self.build(start=True, agents={
            "helper": {"display_name": "Helper", "prompt": "You help.", "models": ["fake/small", "fake/large"],
                       "description": "A helpful agent", "aliases": ["Help"]},
            "p": {"parts": [{"name": "extra", "text": "Be brief."}]}},  # parts for core.yml's other agent, as before
            assignments={"chat:help": {"engine": "probe", "personas": ["helper"]}})
        helper = core.manager.personas["helper"]
        self.assertEqual((helper.profile, helper.aliases, helper.description), ("helper", ("Help",), "A helpful agent"))
        self.assertEqual(core.providers.candidates("helper"), [{"provider": "fake", "model": "small"},
                                                               {"provider": "fake", "model": "large"}])
        self.assertEqual([part.name for part in core.manager.personas["p"].parts], ["extra"])
        from core.config import ConfigError
        with self.assertRaisesRegex(ConfigError, "`models` or a `profile`"):
            await self.build(agents={"x": {"prompt": "…", "models": ["fake/a"], "profile": "default"}})


if __name__ == "__main__":
    unittest.main()

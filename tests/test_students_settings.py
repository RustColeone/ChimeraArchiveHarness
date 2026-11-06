"""Tests for a student's settings page (extensions/students/panel.py `settings` and `settle`, memory.py `Page`): the four
tabs the owner reads, a save that lands whole and is used at once, the page's word kept over the settings until they
say something new, and starting over from it."""

import json
import tempfile
import unittest
from pathlib import Path

import mneme_llm.gut as G
import mneme_llm.surface as surface

from contracts import ViewError
from tests import test_momochat as room
from tests.core_support import ROOT, FakeAdapter, iface, make_config, settle, start_core
from tests.test_students_gut import Head

SAVE = {"her": {"name": "Gippy", "language": "japanese", "zone": "UTC+8", "card": {"text": "You are Gippy.", "on": True}},
        "me": {"name": "Boss", "link": ["discord:42"]}, "others": "friend",
        "people": [{"subject": "chat:alice", "role": "family", "closeness": 80, "hold": True,
                    "tune": [{"end": "trusting", "nature": 4}]}],
        "memory": {"surface_days": 9, "said_budget": 3000, "said_words": .5},
        "rows": {"classmates": False}, "gut": {"tau": 300}}


class SettingsPage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.core = None

    async def asyncTearDown(self):
        if self.core is not None:
            await self.core.stop()
        self._tmp.cleanup()

    async def start(self, head, settings=None):
        """The core with GPT (who has a gut) for the owner, alice; again over the same files when it is running."""
        if self.core is not None:
            await self.core.stop()
        self.core = await start_core(self.tmp, {
            "owners": {"chat": ["alice"]},
            "extensions": [*make_config(self.tmp).raw["modules"]["paths"], str(ROOT / "extensions" / "students")],
            "extension_config": {"students": {"learn": True, "language": "en", "embed": False,
                                              "roles": {"chat:alice": "friend"}, "gut": False,
                                              "students": {"gpt": {"gut": True}}, **(settings or {})}},
            "profiles": {name: [{"provider": "fake", "model": name}]
                         for name in ("gpt", "gemini", "claude", "deepseek", "grok")},
            "assignments": {"*": {"engine": "momochat", "personas": ["gpt"]}}}, FakeAdapter(handler=head))
        self.guts().starters.clear()  # (born blank: what these tests check is what the page changes)
        return iface(self.core)

    async def say(self, chat, text, sender="alice"):
        await chat.say(text, conversation="dm", sender=sender, is_direct=True)
        await settle(self.core)
        await self.core.manager.idle()
        return chat.texts("dm")[-1]

    def book(self):
        watcher = next(watcher for watcher, _ in self.core.manager.watchers if watcher.name == "memory")
        return watcher.run.__closure__[0].cell_contents

    def guts(self):
        return next(watcher.run.__self__ for watcher, _ in self.core.manager.watchers if watcher.name == "gut")

    async def awake(self, chat):
        await self.say(chat, "hello")
        gut = self.guts().of("gpt")
        await gut.waking
        return gut

    async def save(self, chat, save, sender="alice"):
        return await self.say(chat, "$settings gpt " + json.dumps(save, ensure_ascii=False), sender)

    async def test_the_owner_reads_her_four_tabs(self):
        script = room.Script(GPT=[room.turn(str(n)) for n in range(4)])
        chat = await self.start(Head(script))
        await self.awake(chat)
        await self.say(chat, "one")  # (a lesson: the first message only woke her gut)
        shown = await chat.port.view("students.settings", "gpt", "alice")
        self.assertEqual((shown["student"], shown["companion"], shown["her"]["name"], shown["her"]["language"],
                          shown["her"]["zone"]), ("gpt", "GPT", "GPT", "auto", ""))
        you = shown["people"][0]
        self.assertEqual((you["subject"], you["you"], you["role"], you["gut"]["lessons"]), ("chat:alice", True, "friend", 1))
        self.assertEqual((shown["others"], shown["me"], shown["starts"]),
                         ("acquaintance", {"name": "", "accounts": [], "fixed": []}, ["fresh", "deep", "gut"]))
        self.assertEqual(shown["memory"], {"surface_days": surface.DAYS, "surface_floor": surface.FLOOR,
                                           "surface_cap": surface.CAP, "surface_window": surface.WINDOW,
                                           "said_budget": 6000, "said_words": shown["memory"]["said_words"]})
        rows = {row["key"]: row for row in shown["rows"]}
        self.assertTrue(rows["models"]["kind"] == "info" and rows["models"]["value"])
        self.assertEqual((rows["learn"]["value"], rows["classmates"]["value"], rows["learn"]["tab"]), (True, True, "memory"))
        self.assertIn("friend", [role["key"] for role in shown["roles"]])
        self.assertEqual(len(shown["gut"]["ends"]), len(G.ENDS))
        with self.assertRaises(ViewError) as caught:
            await chat.port.view("students.settings", "gpt", "bob")  # not the owner
        self.assertEqual(caught.exception.code, "forbidden")
        other = await chat.port.view("students.settings", "gemini", "alice")  # a student without a gut
        self.assertEqual((other["gut"], other["starts"], other["her"]["name"]), (None, ["fresh", "deep"], "Gemini"))

    async def test_a_save_lands_whole_and_is_used_at_once(self):
        script = room.Script(GPT=[room.turn(str(n)) for n in range(6)])
        chat = await self.start(Head(script))
        gut = await self.awake(chat)
        self.assertIn("GPT's settings: saved", await self.save(chat, SAVE))
        book = self.book()
        memory, own = book.open("gpt"), book.settings.of("gpt")
        self.assertEqual((memory.config.get("companion.zone"), memory.surface.span, memory.said_words,
                          memory.display_language), ("UTC+8", 9, .5, "ja"))
        self.assertEqual((own.said, own.reply_language, own.met_role, own.classmates, own.surface_limits),
                         (3000, "japanese", "friend", False, {"surface_days": 9}))
        self.assertEqual((book.calling("gpt", "chat:alice")["name"], book.person("discord:42")), ("Boss", "chat:alice"))
        relationship = memory.relations.get("chat:alice")
        self.assertEqual((relationship.role, round(relationship.closeness), "chat:alice" in memory.relations.locks()),
                         ("family", 80, True))
        card = memory.surface.card("chat:alice")
        self.assertEqual((card.text, card.on), ("You are Gippy.", True))
        self.assertEqual((gut.net.tau, gut.settings["people"]["chat:alice"]["nudge"]), (300.0, {"trusting": 4.0}))
        shown = await chat.port.view("students.settings", "gpt", "alice")
        self.assertEqual((shown["her"]["name"], shown["me"]["accounts"], shown["me"]["name"], book.shown("gpt")),
                         ("Gippy", ["discord:42"], "Boss", "GPT"))  # (her name is hers from the next start)
        await self.say(chat, "how are you?")
        self.assertIn("Reply in Japanese.", script.seen("GPT"))  # (her gut says the language she answers in)
        # A save that fails changes nothing; starting over is sent alone; the page is the owner's.
        self.assertIn("Not saved: memory.surface_days",
                      await self.save(chat, {"her": {"zone": "UTC+9"}, "memory": {"surface_days": 0}}))
        self.assertIn("Not saved: start is sent alone", await self.save(chat, {"start": "fresh", "her": {"zone": "UTC+9"}}))
        self.assertIn("Not saved: discord:43 is not one of your accounts",
                      await self.save(chat, {"me": {"unlink": ["discord:43"]}}))
        self.assertEqual(memory.config.get("companion.zone"), "UTC+8")
        await self.save(chat, {"her": {"zone": "UTC+9"}}, sender="bob")
        self.assertEqual(memory.config.get("companion.zone"), "UTC+8")
        # The language back to each person's own: her memory's lines in the settings' language again.
        await self.save(chat, {"her": {"language": "auto"}, "me": {"unlink": ["discord:42"]}})
        self.assertEqual((memory.display_language, book.person("discord:42")), ("en", "discord:42"))

    async def test_the_page_keeps_its_word_until_the_settings_say_something_new(self):
        script = room.Script(GPT=[room.turn(str(n)) for n in range(6)])
        chat = await self.start(Head(script))
        await self.awake(chat)
        await self.save(chat, {"her": {"name": "Gippy"}, "others": "friend", "rows": {"mood": False},
                               "people": [{"subject": "chat:alice", "role": "family"}]})
        kept = json.loads((self.tmp / "data" / "extensions" / "students" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(kept["gpt"]), ["display_name", "met_role", "mood", "role:chat:alice"])
        chat = await self.start(Head(script))  # the next start: her page's name is hers, and `roles:` gives no role back
        book = self.book()
        self.assertEqual((book.shown("gpt"), book.open("gpt").relations.get("chat:alice").role), ("Gippy", "family"))
        self.assertEqual((book.settings.of("gpt").met_role, book.settings.of("gpt").mood), ("friend", False))
        chat = await self.start(Head(script), {"met_role": "family", "roles": {"chat:alice": "creator"},
                                               "students": {"gpt": {"gut": True, "mood": False}}})
        book = self.book()  # what the settings say now is the latest word, where it changed
        self.assertEqual((book.settings.of("gpt").met_role, book.open("gpt").relations.get("chat:alice").role,
                          book.shown("gpt"), book.settings.of("gpt").mood), ("family", "creator", "Gippy", False))
        file = self.tmp / "data" / "extensions" / "students" / "settings.json"
        await self.save(chat, {"rows": {"mood": True}})
        self.assertEqual(json.loads(file.read_text(encoding="utf-8"))["gpt"]["mood"], {"value": True, "config": False})
        await self.save(chat, {"rows": {"mood": False}})  # (the settings' own value: the page's goes)
        self.assertNotIn("mood", json.loads(file.read_text(encoding="utf-8"))["gpt"])

    async def test_accounts_the_settings_join_stay(self):
        script = room.Script(GPT=[room.turn(str(n)) for n in range(4)])
        chat = await self.start(Head(script), {"people": {"Alice": ["chat:alice", "discord:7"]}})
        await self.awake(chat)
        shown = await chat.port.view("students.settings", "gpt", "alice")
        self.assertEqual((shown["me"]["accounts"], shown["me"]["fixed"]), (["discord:7"], ["discord:7"]))
        self.assertIn("discord:7 is joined to you in the students' settings",
                      await self.save(chat, {"me": {"unlink": ["discord:7"]}}))
        self.assertIn("Not saved: chat:alice is you", await self.save(chat, {"me": {"link": ["chat:alice"]}}))

    async def test_starting_over_from_the_page_keeps_her_card(self):
        script = room.Script(GPT=[room.turn(str(n)) for n in range(8)])
        chat = await self.start(Head(script))
        await self.awake(chat)
        await self.save(chat, {"her": {"card": {"text": "You are GPT.", "on": True}}})
        await self.say(chat, "one")
        memory = self.book().open("gpt")
        self.assertTrue(memory.surface.read("chat:alice").messages)
        await self.save(chat, {"start": "fresh"})
        self.assertEqual((memory.surface.read("chat:alice").messages, memory.episodes.count("chat:alice") > 0), ([], True))
        await self.save(chat, {"start": "deep"})
        card = memory.surface.card("chat:alice")
        self.assertEqual((memory.episodes.count("chat:alice"), card.text, card.on), (0, "You are GPT.", True))
        await self.say(chat, "two")
        self.assertIn("gone for good", await self.say(chat, "$new deep gpt"))
        self.assertEqual(memory.surface.card("chat:alice").text, "You are GPT.")  # (`$new deep` keeps it too)
        lessons = self.guts().of("gpt").report()["lessons"]
        self.assertGreater(lessons, 0)
        await self.save(chat, {"start": "gut"})
        self.assertEqual(self.guts().of("gpt").report()["lessons"], 0)


if __name__ == "__main__":
    unittest.main()

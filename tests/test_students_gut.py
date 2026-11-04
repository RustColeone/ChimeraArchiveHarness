"""Tests for a student's gut (extensions/students/gut.py): what stays of her without her memory or her model."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import mneme_llm.gut as G

from tests import test_momochat as room
from tests.core_support import ROOT, FakeAdapter, iface, make_config, settle, start_core
from tests.test_students_memory import Mind


FORM = {"people": ["coworker"], "gender": ["woman"], "topic": ["lunch"], "event": ["ate"], "sender_feels": "happy",
        "toward_you": "none"}
OTHER = {"people": [], "gender": [], "topic": ["rain"], "event": ["rained"], "sender_feels": "tired", "toward_you": "none"}
JEALOUS = {"jealous": .8, "sweet": .2}


class Head(Mind):
    """Her reading, vote and note, beside what Mind answers."""

    def __init__(self, script):
        super().__init__(script)
        self.reads, self.votes, self.notes, self.shapes = [], [], [], []
        self.fail, self.side = set(), None

    def __call__(self, messages, schema):
        system, last = messages[0]["content"], messages[-1]["content"]
        if system.startswith("You read one chat message"):
            self.reads.append(last)
            if "read" in self.fail:
                raise RuntimeError("no")
            return {**FORM, "language": "en"}
        if system.startswith(G.SHAPE):
            self.shapes.append(messages)
            if "shape" in self.fail:
                raise RuntimeError("no")
            return {"side": self.side}
        if "一直想让她变成这样" in last:
            return {"name": "小绿茶", "what": "你先夸她，再让她显得不如你。"}
        if G.ASK in last:
            self.votes.append(messages)
            if "vote" in self.fail:
                raise RuntimeError("no")
            return JEALOUS
        if G.NOTE in last:
            self.notes.append(messages)
            return {"mood": 1, "feel": JEALOUS} if "note" not in self.fail else "no idea"
        return super().__call__(messages, schema)


class Turns(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.core = None

    async def asyncTearDown(self):
        if self.core is not None:
            await self.core.stop()
        self._tmp.cleanup()

    async def start(self, head, gut=True, role="friend", owner=False):
        self.core = await start_core(self.tmp, {
            **({"owners": {"chat": ["alice"]}} if owner else {}),
            "extensions": [*make_config(self.tmp).raw["modules"]["paths"], str(ROOT / "extensions" / "students")],
            "extension_config": {"students": {"learn": True, "language": "en", "roles": {"chat:alice": role},
                                              "students": {"gpt": {"gut": gut}}}},
            "profiles": {name: [{"provider": "fake", "model": name}] for name in ("gpt", "gemini", "claude", "deepseek", "grok")},
            "assignments": {"*": {"engine": "momochat", "personas": ["gpt"]}}}, FakeAdapter(handler=head))
        return iface(self.core)

    async def say(self, chat, text):
        await chat.say(text, conversation="dm", sender="alice")
        await settle(self.core)
        await self.core.manager.idle()
        return chat.texts("dm")[-1]

    def guts(self):
        return next(watcher.run.__self__ for watcher, _ in self.core.manager.watchers if watcher.name == "gut")

    async def awake(self, chat):
        """The first message wakes her gut beside it."""
        await self.say(chat, "hello")
        gut = self.guts().of("gpt")
        await gut.waking
        self.assertTrue(gut.awake)
        return gut

    async def test_the_line_is_beside_the_message_and_her_answer_is_untouched(self):
        script = room.Script(GPT=[room.turn("Hi."), room.turn("Oh, a coworker. Nice.")])
        head = Head(script)
        chat = await self.start(head)
        gut = await self.awake(chat)
        self.assertEqual(await self.say(chat, "had lunch with a coworker"), "Oh, a coworker. Nice.")
        turn = script.seen("GPT")
        self.assertIn("(Right now you feel very jealous, a little sweet, and it shows in how you answer.)", turn)
        self.assertIn("Reply in English.", turn)
        self.assertEqual(head.reads, ["had lunch with a coworker"])  # no history in her reading
        self.assertIn("(Alice is ", head.votes[-1][-1]["content"])  # her memory in her vote
        self.assertEqual(gut.report()["lessons"], 1)
        self.assertEqual(json.loads(sqlite3.connect(gut.path).execute("select feel from lessons").fetchone()[0]), JEALOUS)
        self.assertEqual(head.notes[-1][-2], {"role": "assistant", "content": "Oh, a coworker. Nice."})
        self.assertIn("Right now you feel", head.notes[-1][0]["content"])  # the line stays in view of her note
        said = sqlite3.connect(gut.path).execute("select form, feel from lessons").fetchall()
        self.assertNotIn("had lunch", json.dumps(said))  # forms and feelings, never messages

    async def test_a_turn_without_a_gut_asks_nothing(self):
        script = room.Script(GPT=[room.turn("Hi.")])
        head = Head(script)
        chat = await self.start(head, gut=False)
        await self.say(chat, "hello")
        self.assertEqual((head.reads, head.votes, head.notes), ([], [], []))
        self.assertNotIn("Right now", script.seen("GPT"))

    async def test_she_answers_when_her_reading_or_her_vote_fails(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b"), room.turn("c"), room.turn("d")])
        head = Head(script)
        chat = await self.start(head)
        gut = await self.awake(chat)
        head.fail = {"read"}
        self.assertEqual(await self.say(chat, "one"), "b")
        self.assertIn("very jealous", script.seen("GPT"))  # her head alone
        self.assertEqual(gut.report()["lessons"], 0)  # no form, no lesson
        head.fail = {"vote"}
        self.assertEqual(await self.say(chat, "two"), "c")
        self.assertEqual(gut.report()["lessons"], 1)
        head.fail = {"read", "vote"}
        self.assertEqual(await self.say(chat, "three"), "d")
        self.assertNotIn("Right now", script.seen("GPT"))

    async def test_a_slow_call_does_not_hold_her_up_and_its_reading_still_teaches(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head)
        gut = await self.awake(chat)
        real = G.Turn.__init__
        slow = asyncio.Event()

        def begin(turn, gut, ask, prompt, said, subject):
            async def slowed(messages, tokens, *more):
                if messages[0]["content"] == G.FORM:
                    await slow.wait()
                return await ask(messages, tokens, *more)
            real(turn, gut, slowed, prompt, said, subject)
        G.Turn.__init__, limit, G.TIME_LIMIT = begin, G.TIME_LIMIT, .05
        self.addCleanup(setattr, G, "TIME_LIMIT", limit)
        self.addCleanup(setattr, G.Turn, "__init__", real)
        await chat.say("two", conversation="dm", sender="alice")
        await settle(self.core)
        for _ in range(100):
            if "b" in chat.texts("dm"):
                break
            await asyncio.sleep(.01)
        self.assertIn("b", chat.texts("dm"))  # she answered with her reading still out
        self.assertIn("very jealous", script.seen("GPT"))  # on her vote
        slow.set()
        await self.core.manager.idle()
        self.assertEqual(gut.report()["lessons"], 1)

    async def test_no_note_no_lesson_and_it_is_only_logged(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head)
        gut = await self.awake(chat)
        head.fail = {"note"}
        self.assertEqual(await self.say(chat, "one"), "b")
        self.assertEqual(gut.report()["lessons"], 0)
        self.assertEqual(len(head.notes), 2)  # asked twice ("hello" came before she woke: not asked)

    async def test_a_stranger_gets_her_gut_and_teaches_only_how_she_is_with_them(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head, role="acquaintance")
        gut = await self.awake(chat)
        await self.say(chat, "one")
        self.assertIn("very jealous", script.seen("GPT"))
        found = gut.report()
        self.assertEqual((found["lessons"], found["age"], len(found["people"])), (1, 0, 1))  # not her heart

    async def test_wiping_her_memory_leaves_her_gut(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b"), room.turn("c")])
        head = Head(script)
        chat = await self.start(head)
        gut = await self.awake(chat)
        await self.say(chat, "one")
        self.assertEqual(gut.report()["lessons"], 1)
        folder = self.tmp / "data" / "extensions" / "students"
        self.assertTrue((folder / "gut" / "gpt.db").is_file() and (folder / "gpt.db").is_file())

    async def test_in_a_group_chat_only_the_student_with_a_gut_feels_it(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")], Gemini=[room.turn("c"), room.turn("d")])
        head = Head(script)
        self.core = await start_core(self.tmp, {
            "extensions": [*make_config(self.tmp).raw["modules"]["paths"], str(ROOT / "extensions" / "students")],
            "extension_config": {"students": {"learn": True, "language": "en", "roles": {"chat:alice": "friend"},
                                              "students": {"gpt": {"gut": True}}}},
            "profiles": {name: [{"provider": "fake", "model": name}] for name in ("gpt", "gemini", "claude", "deepseek", "grok")},
            "assignments": {"*": {"engine": "momochat", "personas": ["gpt", "gemini"]}}}, FakeAdapter(handler=head))
        chat = iface(self.core)
        for text in ("GPT, Gemini, hello", "GPT, Gemini, how are you"):
            await chat.say(text, conversation="room", sender="alice")
            await settle(self.core)
            await self.core.manager.idle()
            await self.guts().of("gpt").waking
        self.assertIn("Right now you feel", script.seen("GPT"))
        self.assertNotIn("Right now you feel", script.seen("Gemini"))
        self.assertEqual(self.guts().of("gpt").report()["lessons"], 1)  # (the first message woke her)

    async def days(self, chat, days):
        """A message a day, on her gut's clock."""
        real, clock = G.time, SimpleNamespace(monotonic=G.time.monotonic)
        G.time = clock
        self.addCleanup(setattr, G, "time", real)
        for day in days:
            clock.time = lambda day=day: real.time() + day * 86400
            await self.say(chat, "你好绿茶")
        G.time = real

    async def test_a_side_grows_over_days_stays_when_her_memory_goes_and_objecting_ends_it(self):
        script = room.Script(GPT=[room.turn(str(n)) for n in range(30)])
        head = Head(script)
        chat = await self.start(head, role="family")
        gut = await self.awake(chat)
        await self.say(chat, "hello again")
        self.assertEqual(gut.sightings, [])  # ordinary chat: nothing noted, and the reading was still asked
        self.assertEqual(len(head.shapes), 1)
        head.side = {"name": "绿茶", "more": True, "what": "说别的女生不好"}
        await self.days(chat, range(3))
        self.assertEqual(gut.report()["sides"], {})  # three days is not enough, even for family
        self.assertIn("绿茶 (说别的女生不好)", head.shapes[-1][0]["content"])  # she noted it under one name
        await self.days(chat, range(3, 7))
        self.assertEqual(gut.report()["sides"], {"小绿茶": "你先夸她，再让她显得不如你。"})
        head.side = None
        await self.say(chat, "嗯")
        self.assertIn("(Right now your 小绿茶 side is showing: 你先夸她，再让她显得不如你。)", script.seen("GPT"))
        self.assertIn("(Right now your 小绿茶 side is showing", head.notes[-1][0]["content"])
        await self.core.stop()
        self.core = None
        for path in (self.tmp / "data" / "extensions" / "students").glob("gpt.db*"):
            path.unlink()
        script = room.Script(GPT=[room.turn(str(n)) for n in range(30)])
        head = Head(script)
        chat = await self.start(head, role="family")
        gut = await self.awake(chat)
        await self.say(chat, "好久不见")
        self.assertIn("(Right now your 小绿茶 side is showing", script.seen("GPT"))
        head.side = {"name": "端着", "more": False, "what": "别这样"}
        for _ in range(8):
            await self.say(chat, "别这样了")
        self.assertEqual(gut.report()["sides"], {})
        head.side = None
        await self.say(chat, "嗯")
        self.assertNotIn("side is showing", script.seen("GPT"))

    async def test_a_failed_reading_of_the_person_loses_no_lesson(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head)
        gut = await self.awake(chat)
        head.fail = {"shape"}
        await self.say(chat, "one")
        self.assertEqual(gut.report()["lessons"], 1)

    async def test_who_she_already_is_is_no_side(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head, role="family")
        gut = await self.awake(chat)
        head.side = {"name": "a", "more": True, "what": "x"}  # (a letter of her character)
        await self.say(chat, "one")
        self.assertEqual(gut.sightings, [])

    async def test_the_owner_can_write_and_take_away_a_side(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head, owner=True)
        gut = await self.awake(chat)
        self.assertIn("御姐 side: 你从容", await self.say(chat, "$side gpt 御姐 你从容，从上往下逗对方。"))
        self.assertEqual(gut.report()["sides"], {"御姐": "你从容，从上往下逗对方。"})
        shown = await self.say(chat, "$gut")
        self.assertIn("side 御姐 (6.0): 你从容", shown)
        self.assertIn("she is in 御姐 for 30 more days at least", shown)
        self.assertIn("御姐 side: 3", await self.say(chat, "$side gpt 御姐 3"))
        self.assertEqual(gut.report()["sides"], {"御姐": "你从容，从上往下逗对方。"})  # a number sets how much of her, not her sentence
        self.assertEqual(gut.weight("御姐"), 3)
        self.assertIn("She has no side 三无", await self.say(chat, "$side gpt 三无 3"))
        self.assertIn("Gone: 御姐", await self.say(chat, "$side gpt 御姐 off"))
        self.assertEqual(gut.report()["sides"], {})
        self.assertIn("Use `$side", await self.say(chat, "$side gpt 御姐"))
        self.assertIn("Not a side she can have: 草莓", await self.say(chat, "$side gpt 草莓 你很甜。"))
        self.assertEqual(gut.report()["sides"], {})

    async def test_she_stays_in_one_side_for_a_month(self):
        script = room.Script(GPT=[room.turn(str(n)) for n in range(6)])
        chat = await self.start(Head(script), owner=True)
        gut = await self.awake(chat)
        gut.write_side("御姐", "你从容。", 3)
        gut.write_side("病娇", "你只要他。", 1)
        held = gut.holding()
        await self.say(chat, "嗯")
        self.assertEqual(script.seen("GPT").count("side is showing"), 1)
        self.assertIn(f"your {held[0]} side", script.seen("GPT"))
        self.assertEqual(gut.holding(G.time.time() + 29 * 86400), held)
        for_months = {tuple(gut.holding(G.time.time() + month * G.HOLD)) for month in range(1, 200)}
        self.assertEqual(for_months, {("御姐",), ("病娇",)})

    async def test_a_side_only_takes_a_name_on_the_list(self):
        gut = G.Gut(self.tmp / "list.db")
        gut.wake()
        self.addCleanup(gut.close)
        gut.grow("草莓", {"name": "草莓", "what": "你很甜。"})
        self.assertEqual(gut.grown, {})
        self.assertIn("小绿茶", G.grow_messages("病娇", [], {})[0]["content"])

    async def test_only_the_owner_can_change_her_sides(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head)
        gut = await self.awake(chat)
        await self.say(chat, "$side gpt 御姐 你从容。")
        self.assertEqual(gut.report()["sides"], {})

    async def test_gut_shows_where_she_stands(self):
        script = room.Script(GPT=[room.turn("a"), room.turn("b")])
        head = Head(script)
        chat = await self.start(head)
        await self.awake(chat)
        await self.say(chat, "one")
        shown = await self.say(chat, "$gut")
        self.assertIn("1 lessons", shown)
        self.assertNotIn("told:", shown)  # what she was told is for her owner

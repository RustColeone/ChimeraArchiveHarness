"""Her surface in the real core: `/new` and how deep it goes, what her vote reads, and a person's first prompt."""

import tempfile
import unittest
from pathlib import Path

from tests import test_momochat as room
from tests.core_support import ROOT, FakeAdapter, iface, make_config, settle, start_core
from tests.test_students_gut import Head


class SurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.core = None

    async def asyncTearDown(self):
        if self.core is not None:
            await self.core.stop()
        self._tmp.cleanup()

    async def start(self, head, owner=True, gut=True, surface=True):
        self.core = await start_core(self.tmp, {
            **({"owners": {"chat": ["alice"]}} if owner else {}),
            "extensions": [*make_config(self.tmp).raw["modules"]["paths"], str(ROOT / "extensions" / "students")],
            "extension_config": {"students": {"learn": True, "language": "en", "roles": {"chat:alice": "friend"},
                                              "embed": False, "students": {"gpt": {"gut": gut, "surface": surface}}}},
            "profiles": {name: [{"provider": "fake", "model": name}]
                         for name in ("gpt", "gemini", "claude", "deepseek", "grok")},
            "assignments": {"*": {"engine": "momochat", "personas": ["gpt"]}}}, FakeAdapter(handler=head))
        return iface(self.core)

    async def say(self, chat, text):
        await chat.say(text, conversation="dm", sender="alice", is_direct=True)
        await settle(self.core)
        await self.core.manager.idle()
        return chat.texts("dm")[-1]

    def book(self):
        watcher = next(watcher for watcher, _ in self.core.manager.watchers if watcher.name == "memory")
        return watcher.run.__closure__[0].cell_contents

    def memory(self):
        return self.book().open("gpt")

    def gut(self):
        return next(watcher.run.__self__ for watcher, _ in self.core.manager.watchers if watcher.name == "gut").of("gpt")

    async def awake(self, chat):
        await self.say(chat, "hello")
        gut = self.gut()
        await gut.waking
        return gut

    async def test_her_vote_and_note_read_her_copy_and_new_starts_it_over(self):
        head = Head(room.Script(GPT=[room.turn("Hi."), room.turn("Noted."), room.turn("Noted."), room.turn("Hm?")]))
        chat = await self.start(head)
        await self.awake(chat)
        await self.say(chat, "my violin teacher is Anna")
        await self.say(chat, "she moved to Berlin")
        self.assertIn("my violin teacher is Anna", str(head.votes[-1]))
        self.assertIn("my violin teacher is Anna", str(head.notes[-1]))
        self.assertEqual(await self.say(chat, "/new"), "New chat started.")
        await self.say(chat, "who is that?")
        self.assertNotIn("violin", str(head.votes[-1]))
        self.assertNotIn("/new", str(head.votes[-1]))
        self.assertNotIn("violin", str(head.notes[-1]))
        self.assertEqual(self.memory().episodes.count("chat:alice"), 4)  # (deep memory stays)
        self.assertEqual(len(self.memory().surface.read("chat:alice").messages), 2)

    async def test_new_with_her_name_is_a_new_chat_with_her(self):
        script = room.Script(GPT=[room.turn("Noted."), room.turn("Hm?")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        self.assertEqual(await self.say(chat, "/new gpt"), "New chat with GPT.")
        await self.say(chat, "who is that?")
        self.assertNotIn("violin", str(script.prompts["GPT"][-1][:-1]))

    async def test_new_with_another_word_is_a_message(self):
        script = room.Script(GPT=[room.turn("Sure.")])
        chat = await self.start(Head(script), gut=False)
        self.assertEqual(await self.say(chat, "/new year"), "Sure.")

    async def test_new_deep_points_to_the_command(self):
        chat = await self.start(Head(room.Script(GPT=[])), gut=False)
        self.assertIn("$new deep", await self.say(chat, "/new deep"))
        self.assertIn("$new gut", await self.say(chat, "/new gut"))

    async def test_the_deeper_tiers_are_the_creators(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Noted.")])), owner=False, gut=False)
        await self.say(chat, "my violin teacher is Anna")
        self.assertIn("available only to the owner", await self.say(chat, "$new deep gpt"))
        self.assertEqual(self.memory().episodes.count("chat:alice"), 1)

    async def test_the_deeper_tiers_name_who_or_do_nothing(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Noted.")])), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        for text in ("$new deep", "$new gut", "$new everything", "$new deep gpt gemini"):
            self.assertIn("`everyone`", await self.say(chat, text))
        self.assertIn("No student called 'nobody'", await self.say(chat, "$new deep nobody"))
        self.assertEqual(self.memory().episodes.count("chat:alice"), 1)

    async def test_deep_clears_what_she_remembers_and_her_context_and_leaves_who_they_are(self):
        script = room.Script(GPT=[room.turn("Noted."), room.turn("Hm?")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        self.assertIn("1 exchanges gone for good", await self.say(chat, "$new deep gpt"))
        self.assertEqual(self.memory().episodes.count("chat:alice"), 0)
        self.assertEqual(self.memory().relations.get("chat:alice").role, "friend")
        await self.say(chat, "who is that?")
        self.assertNotIn("violin", str(script.prompts["GPT"][-1][:-1]))

    async def test_everyone_is_every_student(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Noted.")])), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        self.assertIn("Every student: 1 exchanges", await self.say(chat, "$new deep everyone"))
        self.assertEqual(self.memory().episodes.count("chat:alice"), 0)

    async def test_deep_leaves_her_gut_and_gut_takes_it(self):
        head = Head(room.Script(GPT=[room.turn("Hi."), room.turn("Noted.")]))
        chat = await self.start(head)
        gut = await self.awake(chat)
        await self.say(chat, "my violin teacher is Anna")
        gut.write_side("御姐", "你从容。")
        await self.say(chat, "$new deep gpt")
        self.assertGreater(gut.report()["lessons"], 0)
        self.assertIn("御姐", gut.grown)
        self.assertIn("lessons of the gut", await self.say(chat, "$new gut gpt"))
        self.assertEqual(gut.report()["lessons"], 0)
        self.assertEqual(gut.grown, {})

    async def test_the_first_thing_said_is_kept_and_the_person_can_change_it(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Yes."), room.turn("Ok.")])), owner=False, gut=False)
        await self.say(chat, "you are my big sister")
        await self.say(chat, "long day")
        shown = await self.say(chat, "$first")
        self.assertIn("you are my big sister", shown)
        self.assertIn("the first thing you said", shown)
        self.assertIn("Kept, for GPT", await self.say(chat, "$first gpt talk less"))
        shown = await self.say(chat, "$first gpt")
        self.assertIn("talk less", shown)
        self.assertIn("you set this", shown)
        self.assertIn("only kept", shown)
        self.assertIn("Taken away", await self.say(chat, "$first clear"))
        self.assertIn("nothing kept yet", await self.say(chat, "$first"))
        self.assertIn("no first prompt yet", await self.say(chat, "$first on"))

    async def test_a_new_chat_is_the_first_prompt_the_surface_and_the_new_message(self):
        script = room.Script(GPT=[room.turn("Yes."), room.turn("Ok.")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        await self.say(chat, "$first talk less")
        await self.say(chat, "$first on")
        await chat.say("hello again", conversation="dm2", sender="alice", is_direct=True)
        await settle(self.core)
        messages = script.prompts["GPT"][-1]
        self.assertEqual(messages[1], {"role": "user", "content": "talk less\n\nmy violin teacher is Anna"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "Yes."})
        self.assertTrue(messages[3]["content"].endswith("hello again"))

    async def test_off_a_new_chat_is_the_surface_and_the_new_message(self):
        script = room.Script(GPT=[room.turn("Yes."), room.turn("Ok.")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        await chat.say("hello again", conversation="dm2", sender="alice", is_direct=True)
        await settle(self.core)
        self.assertEqual(script.prompts["GPT"][-1][1], {"role": "user", "content": "my violin teacher is Anna"})

    async def test_after_new_only_the_first_prompt_is_left_in_front(self):
        script = room.Script(GPT=[room.turn("Yes."), room.turn("Ok.")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        await self.say(chat, "$first talk less")
        await self.say(chat, "$first on")
        await self.say(chat, "/new")
        await self.say(chat, "hi again")
        messages = script.prompts["GPT"][-1]
        self.assertTrue(messages[1]["content"].startswith("talk less\n\n[This turn's context"))
        self.assertEqual(len(messages), 2)  # (no turns of before, and not "New chat started.")

    async def test_the_surface_reads_far_past_the_engines_window_and_only_what_is_newer_comes_from_it(self):
        script = room.Script(GPT=[room.turn("Ok.")])
        chat = await self.start(Head(script), gut=False)
        memory = self.book().open("gpt", create=True)
        for number in range(120):
            memory.episodes.keep("chat:alice", [("Alice", f"message number {number} "), ("GPT", "ok")], at=1000.0 + number,
                                 conversation="chat:dm")
        await self.say(chat, "latest")
        prompt = str(script.prompts["GPT"][-1])
        self.assertIn("'message number 0'", prompt)
        self.assertEqual(prompt.count("'message number 119'"), 1)

    async def test_a_group_keeps_the_engines_own_window(self):
        script = room.Script(GPT=[room.turn("Hm.")])
        chat = await self.start(Head(script), gut=False)
        memory = self.book().open("gpt", create=True)
        memory.episodes.keep("chat:alice", [("Alice", "said in private"), ("GPT", "ok")], at=1000.0, conversation="chat:dm")
        await chat.say("GPT, hello", conversation="room", sender="alice", is_direct=False, mentions_me=True)
        await settle(self.core)
        self.assertNotIn("said in private", str(script.prompts["GPT"][-1]))  # (and no search brings it either)

    async def test_turned_off_she_reads_the_engines_own_window(self):
        script = room.Script(GPT=[room.turn("Hm.")])
        chat = await self.start(Head(script), gut=False, surface=False)
        memory = self.book().open("gpt", create=True)
        memory.episodes.keep("chat:alice", [("Alice", "said long ago"), ("GPT", "ok")], at=1000.0, conversation="chat:dm")
        await self.say(chat, "hello")
        self.assertNotIn("said long ago", str(script.prompts["GPT"][-1][:-1]))

    async def test_what_she_said_on_her_own_stays_in_what_she_reads(self):
        script = room.Script(GPT=[room.turn("Thinking of you."), room.turn("Good.")])
        chat = await self.start(Head(script), gut=False)
        memory = self.book().open("gpt", create=True)
        memory.episodes.keep("chat:alice", [("", "(You messaged them on your own then: 想他了)"), ("GPT", "I missed you")],
                             at=1000.0)
        await self.say(chat, "what did you say?")
        self.assertEqual(script.prompts["GPT"][-1][1:3], [
            {"role": "user", "content": "(You messaged them on your own then: 想他了)"},
            {"role": "assistant", "content": "I missed you"}])


if __name__ == "__main__":
    unittest.main()

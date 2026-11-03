"""Her surface in the real core: `/new` and how deep it goes, what her vote reads, and a person's first prompt."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from contracts import Address, Sender
from core.manager.threads import thread_key
from tests import test_momochat as room
from tests.core_support import ROOT, FakeAdapter, iface, make_config, settle, start_core
from tests.test_students_gut import Head


class Interrupted(FakeAdapter):
    """A person writes while her model thinks: `words` come in on the model calls they are numbered by."""

    def __init__(self, handler, words):
        super().__init__(handler=handler)
        self.words, self.chat, self.count = dict(words), None, 0

    async def complete(self, *arguments, **options):
        self.count += 1
        if self.count in self.words:
            await self.chat.say(self.words[self.count], conversation="dm", sender="alice", is_direct=True)
        return await super().complete(*arguments, **options)


class SurfaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.core = None

    async def asyncTearDown(self):
        if self.core is not None:
            await self.core.stop()
        self._tmp.cleanup()

    async def start(self, head, owner=True, gut=True, surface=True, personas=("gpt",), options=None, settings=None,
                    adapter=None):
        self.core = await start_core(self.tmp, {
            **({"owners": {"chat": ["alice"]}} if owner else {}),
            "extensions": [*make_config(self.tmp).raw["modules"]["paths"], str(ROOT / "extensions" / "students")],
            "extension_config": {"students": {"learn": True, "language": "en", "roles": {"chat:alice": "friend"},
                                              "embed": False, "students": {"gpt": {"gut": gut, "surface": surface}},
                                              **(settings or {})}},
            "profiles": {name: [{"provider": "fake", "model": name}]
                         for name in ("gpt", "gemini", "claude", "deepseek", "grok")},
            "assignments": {"*": {"engine": "momochat", "personas": list(personas), "options": options or {}}}},
            adapter or FakeAdapter(handler=head))
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

    def lines(self, student="gpt"):
        """All she keeps, line by line, in the order it was said."""
        kept = self.book().open(student).episodes.after("chat:alice", 0)
        return [tuple(line) for item in reversed(kept) for line in item.lines]

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

    async def test_the_answer_to_her_question_is_kept_and_her_next_chat_reads_it(self):
        script = room.Script(GPT=[room.turn("Which city?", "needs_input"), room.turn("Paris it is."), room.turn("Ok.")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "what is the weather?")
        await self.say(chat, "Paris, France")
        self.assertEqual(self.lines(), [("Alice", "what is the weather?"), ("GPT", "Which city?"),
                                        ("Alice", "Paris, France"), ("GPT", "Paris it is.")])
        await chat.say("and tomorrow?", conversation="dm2", sender="alice", is_direct=True)
        await settle(self.core)
        self.assertIn("Paris, France", str(script.prompts["GPT"][-1]))

    async def test_a_message_that_came_while_she_worked_is_kept_and_a_run_keeps_a_persons_words_once(self):
        script = room.Script(GPT=[room.turn("One moment.", "continue", [("basic.now", {})]),
                                  room.turn("Looking.", "continue", [("basic.now", {})]), room.turn("Done.")])
        adapter = Interrupted(Head(script), {2: "and it is urgent"})
        adapter.chat = await self.start(None, gut=False, adapter=adapter)
        await self.say(adapter.chat, "book a table")
        self.assertEqual(self.lines(), [("Alice", "book a table"), ("GPT", "One moment."), ("Alice", "and it is urgent"),
                                        ("GPT", "Looking."), ("GPT", "Done.")])
        self.assertEqual(len(self.core.tank.runs(("done",))), 1)

    async def test_a_message_whose_run_failed_is_kept_with_the_next(self):
        script = room.Script(GPT=[RuntimeError("no model"), room.turn("Back.")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "are you there?")
        await self.say(chat, "hello?")
        self.assertEqual(self.lines(), [("Alice", "are you there?"), ("Alice", "hello?"), ("GPT", "Back.")])

    async def test_commands_and_what_came_before_new_stay_out_of_what_she_keeps(self):
        script = room.Script(GPT=[room.turn("Noted."), room.turn("Hm?")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "$bond")
        await self.say(chat, "my violin teacher is Anna")
        await self.say(chat, "/new")
        await self.say(chat, "who is that?")
        self.assertEqual([said for who, said in self.lines() if who == "Alice"],
                         ["my violin teacher is Anna", "who is that?"])

    async def test_a_group_that_calls_itself_direct_stays_a_group(self):
        script = room.Script(GPT=[room.turn("Hm."), room.turn("Hm.")])
        chat = await self.start(Head(script), gut=False, personas=("gpt", "gemini"))
        memory = self.book().open("gpt", create=True)
        memory.episodes.keep("chat:alice", [("Alice", "said in private"), ("GPT", "ok")], at=1000.0, conversation="chat:dm")
        await chat.say("GPT, hello", conversation="page", sender="alice", is_direct=True, mentions_me=True)
        await settle(self.core)
        self.assertNotIn("said in private", str(script.prompts["GPT"][-1]))  # (like a web page's group chat)

    async def test_new_in_a_group_leaves_what_a_member_keeps_of_a_person(self):
        script = room.Script(GPT=[room.turn("Hm.")], Gemini=[room.turn("Hm.")])
        chat = await self.start(Head(script), gut=False, personas=("gpt", "gemini"))
        memory = self.book().open("gpt", create=True)
        memory.episodes.keep("chat:alice", [("Alice", "said in private"), ("GPT", "ok")], at=1000.0, conversation="chat:dm")
        for text in ("/new", "GPT, hello"):
            await chat.say(text, conversation="room", sender="alice", is_direct=False, mentions_me=True)
            await settle(self.core)
            await self.core.manager.idle()
        self.assertIn("said in private", str(memory.surface.read("chat:alice").messages))

    async def test_a_new_chat_reads_only_its_own_window_of_what_she_did_not_answer_there(self):
        script = room.Script(GPT=[room.turn("Hello.")])
        chat = await self.start(Head(script), gut=False, options={"history_limit": 2})
        memory = self.book().open("gpt", create=True)
        memory.episodes.keep("chat:alice", [("Alice", "from the other chat"), ("GPT", "ok")], at=1000.0, conversation="chat:dm")
        now = time.time()
        for number in range(5):
            await chat.port.observe(Address("chat", "new"), f"unanswered {number}", sender=Sender("alice", "Alice"),
                                    message_id=f"m{number}", at=now - 50 + number)
        await chat.say("hi", conversation="new", sender="alice", is_direct=True)
        await settle(self.core)
        prompt = str(script.prompts["GPT"][-1])
        self.assertIn("from the other chat", prompt)
        self.assertNotIn("unanswered 2", prompt)
        self.assertIn("unanswered 4", prompt)

    async def test_what_a_classmate_heard_is_kept_when_it_was_said(self):
        script = room.Script(GPT=[room.turn("Hm.")])
        chat = await self.start(Head(script), gut=False, personas=("gpt", "gemini"))
        await chat.say("GPT, hello", conversation="room", sender="alice", is_direct=False, mentions_me=True)
        await settle(self.core)
        await self.core.manager.idle()
        hers = self.book().open("gpt").episodes.after("chat:alice", 0)[0]
        heard = self.book().open("gemini").episodes.after("chat:alice", 0)[0]
        self.assertEqual((heard.at, heard.conversation), (hers.at, hers.conversation))

    async def test_she_lets_go_of_her_surface_only_when_she_reads_one(self):
        script = room.Script(GPT=[room.turn("Hm."), room.turn("Hm.")])
        for surface, calls in ((False, 0), (True, 1)):
            chat = await self.start(Head(script), gut=False, surface=surface)
            memory = self.book().open("gpt", create=True)
            memory.surface.alet_go = AsyncMock(return_value=False)
            await self.say(chat, "hello")
            self.assertEqual(memory.surface.alet_go.await_count, calls)
            await self.core.stop()
            self.core = None

    async def test_a_turn_reads_what_she_keeps_once_and_the_conversation_once_a_step(self):
        script = room.Script(GPT=[room.turn("One.", "continue", [("basic.now", {})]),
                                  room.turn("Two.", "continue", [("basic.now", {})]), room.turn("Three.")])
        chat = await self.start(Head(script), gut=False)
        self.book().open("gpt", create=True).episodes.keep("chat:alice", [("Alice", "hi"), ("GPT", "hi")], at=1000.0)
        self.core.manager.watchers.clear()
        manager, tank = self.core.manager, self.core.tank
        kept, thread = [], []
        read, recent = manager.context_of, tank.recent_messages
        manager.context_of = lambda *values: (kept.append(1), read(*values))[1]
        tank.recent_messages = lambda address, limit=30: (thread.append(limit), recent(address, limit))[1]
        await self.say(chat, "go")
        self.assertEqual(len(kept), 1)
        self.assertEqual(thread.count(200), 4)  # (each of the three steps, and the look at folding when the run opens)

    async def test_new_with_her_name_is_a_new_chat_with_her(self):
        script = room.Script(GPT=[room.turn("Noted."), room.turn("Hm?")])
        chat = await self.start(Head(script), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        self.assertEqual(await self.say(chat, "/new gpt"), "New chat with GPT.")
        await self.say(chat, "who is that?")
        self.assertNotIn("violin", str(script.prompts["GPT"][-1][:-1]))

    async def test_new_with_another_word_is_a_message(self):
        script = room.Script(GPT=[room.turn("Sure."), room.turn("Deep?")])
        chat = await self.start(Head(script), gut=False)
        self.assertEqual(await self.say(chat, "/new year"), "Sure.")
        self.assertEqual(await self.say(chat, "/new deep"), "Deep?")

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

    async def test_threads_are_the_cores_and_new_starts_one_at_each_level(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Noted.")])), gut=False)
        await self.say(chat, "/new")
        await self.say(chat, "/new gpt")
        await self.say(chat, "$new deep gpt")
        started = self.core.tank.store("core:threads")
        self.assertEqual(set(started.keys()), {thread_key("chat:dm"), thread_key("chat:dm", "gpt"), thread_key("", "gpt")})
        self.assertEqual(self.core.tank.store("persona:gpt").keys(), [])

    async def test_deep_is_critical_and_runs_at_once_for_the_owner_who_typed_it(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Noted.")])), gut=False)
        await self.say(chat, "my violin teacher is Anna")
        self.assertEqual(self.core.manager.capabilities["students.new"].risk.value, "critical")
        self.assertIn("gone for good", await self.say(chat, "$new deep gpt"))
        self.assertEqual(self.memory().episodes.count("chat:alice"), 0)
        self.assertEqual(iface(self.core, "owner").notices("approval_request"), [])

    async def test_deep_takes_what_she_had_coming_off_the_pages(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Noted.")])), gut=False)
        await self.say(chat, "I fly to Berlin tomorrow")
        memory, facts = self.memory(), self.core.manager.facts
        memory.remember("chat:alice", "Flies to Berlin", kind="plan", happened_at=time.time() + 3600)
        self.book().publish(facts.handle("students"), "gpt", "chat:alice")
        self.assertTrue(facts.read("gpt", ("chat", "alice"))["students.plans"])
        await self.say(chat, "$new deep gpt")
        self.assertNotIn("students.plans", facts.read("gpt", ("chat", "alice")))

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

    async def test_asking_about_the_first_prompt_makes_no_file_and_says_what_there_is(self):
        chat = await self.start(Head(room.Script()), owner=False, gut=False, settings={"roles": {}})
        self.assertIn("no first prompt yet", await self.say(chat, "$first on"))
        self.assertIn("no first prompt yet", await self.say(chat, "$first off"))
        self.assertIn("Nothing is kept", await self.say(chat, "$first clear"))
        self.assertEqual(list(self.book().folder.glob("*.db")), [])
        self.assertIn("in every direct chat", await self.say(chat, "$first gpt talk less"))
        self.assertIn("in every direct chat", await self.say(chat, "$first gpt on"))
        self.assertIn("she reads it first in every direct chat", await self.say(chat, "$first gpt"))

    async def test_the_first_thing_said_is_kept_with_mood_and_notes_off(self):
        chat = await self.start(Head(room.Script(GPT=[room.turn("Yes.")])), owner=False, gut=False,
                                settings={"mood": False, "notes": False})
        await self.say(chat, "you are my big sister")
        self.assertIn("you are my big sister", await self.say(chat, "$first gpt"))

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

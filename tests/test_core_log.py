"""The log (core/manager/logbook.py): what happened in a conversation, written by the core after each write that ran,
read by engines and by people with `$log`."""

import tempfile
import unittest
from pathlib import Path

from contracts import Address
from core.manager.handles import HistoryHandle
from core.manager.logbook import LINES_KEPT, LogbookHandle
from core.storage.tank import Tank
from tests.core_support import FakeAdapter, iface, settle, start_core, turn_context

ANSWER = {"message": "ok", "status": "complete", "actions": []}
MOMOCHAT = {"assignments": {"*": {"engine": "momochat", "personas": ["p"]}}}


class LogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cores = []

    async def asyncTearDown(self):
        for core in self.cores:
            await core.stop()
        self._tmp.cleanup()

    async def core(self, overrides=None, responses=()):
        adapter = FakeAdapter(list(responses))
        core = await start_core(self.tmp, overrides or {}, adapter)
        self.cores.append(core)
        return core, adapter

    def line(self, core, kind, text, subject="", module="reminders", address="chat:room"):
        return core.tank.add_log(address, module, kind, text, subject=subject)

    async def say(self, core, text, sender="alice", conversation="room", **options):
        chat = iface(core)
        await chat.say(text, sender=sender, conversation=conversation, **options)
        await settle(core)
        return chat.texts(conversation)[-1]

    async def test_lines_are_read_in_order_and_by_conversation(self):
        core, _ = await self.core()
        self.line(core, "reminder", "Set a reminder for the dentist")
        self.line(core, "landed", "飞机票已经改到周三")
        book = LogbookHandle(core.manager, "chat:room")
        self.assertEqual([line.kind for line in book.recent()], ["reminder", "landed"])  # the older first
        self.assertEqual([line.kind for line in book.recent(kind="landed")], ["landed"])
        self.assertEqual(LogbookHandle(core.manager, "chat:other").recent(), [])  # filed by conversation

    async def test_the_oldest_lines_go_past_the_limit(self):
        tank = Tank(self.tmp / "tank.db")
        self.addCleanup(tank.close)
        for index in range(5):
            tank.add_log("chat:room", "m", "note", f"line {index}", keep=3)
        self.assertEqual([line.text for line in tank.log_lines("chat:room")], ["line 4", "line 3", "line 2"])
        self.assertGreater(LINES_KEPT, 100)

    async def test_the_core_logs_a_write_that_ran_and_nothing_else(self):
        core, _ = await self.core({"owners": {"chat": ["boss"]}})
        await self.say(core, "$remember the blue folder", sender="boss")
        await self.say(core, "$notes", sender="boss")  # a read
        await self.say(core, "$remember", sender="boss")  # refused: nothing to remember
        lines = core.tank.log_lines("chat:room")
        self.assertEqual([(line.module, line.kind, line.subject) for line in lines], [("core", "command", "boss")])
        self.assertIn("basic.remember", lines[0].text)

    async def test_what_people_typed_is_in_their_log_but_never_shown_to_a_model(self):
        core, adapter = await self.core(MOMOCHAT, [ANSWER])
        self.line(core, "action", "A thing she did")
        await self.say(core, "$remember the secret nickname", sender="boss")
        await self.say(core, "hello")
        context = turn_context(adapter.calls[-1])
        self.assertIn("A thing she did", context)
        self.assertNotIn("basic.remember", context)  # (a typed `$alias` is for one student, not all)

    async def test_her_turn_shows_the_last_lines_and_a_setting_turns_it_off(self):
        core, adapter = await self.core(MOMOCHAT, [ANSWER, ANSWER])
        self.line(core, "command", "what someone typed, not for this")
        self.line(core, "reminder", "Set a reminder for the dentist")
        await self.say(core, "hello")
        context = turn_context(adapter.calls[-1])
        self.assertIn("Done here lately", context)
        self.assertIn("Set a reminder for the dentist", context)
        self.assertNotIn("what someone typed", context)
        await core.stop()
        self.cores.remove(core)
        quiet = {"assignments": {"*": {"engine": "momochat", "personas": ["p"], "options": {"log_lines": 0}}}}
        core, adapter = await self.core(quiet, [ANSWER])
        await self.say(core, "hello again")
        self.assertNotIn("Done here lately", turn_context(adapter.calls[-1]))

    async def test_a_day_old_line_is_not_shown(self):
        core, adapter = await self.core(MOMOCHAT, [ANSWER])
        line = self.line(core, "reminder", "Long ago")
        core.tank.db.execute("UPDATE log SET at=at-90000 WHERE id=?", (line.id,))
        await self.say(core, "hello")
        self.assertNotIn("Long ago", turn_context(adapter.calls[-1]))

    async def test_people_read_their_lines_and_admins_all_of_them_and_each_removes_what_they_see(self):
        core, _ = await self.core({"owners": {"chat": ["boss"]}})
        mine = self.line(core, "action", "About Alice", subject="alice")
        self.line(core, "action", "About Bob", subject="bob")
        everyone = self.line(core, "landed", "A session landed")
        answer = await self.say(core, "$log")
        self.assertIn("About Alice", answer)
        self.assertNotIn("About Bob", answer)
        self.assertNotIn("A session landed", answer)
        admin = await self.say(core, "$log", sender="boss")
        for text in ("About Alice", "About Bob", "A session landed", "#"):
            self.assertIn(text, admin)
        self.assertIn("No line with that ID", await self.say(core, f"$log forget {everyone.id}"))
        self.assertIn("Line removed", await self.say(core, f"$log forget #{mine.id}"))
        self.assertIn("Nothing in this chat's log", await self.say(core, "$log"))
        self.assertIn("Removed 2", await self.say(core, "$log clear", sender="boss"))
        self.assertIn("$log forget", await self.say(core, "$log forget two"))
        self.assertIn("empty", await self.say(core, "$log 3", sender="boss"))

    async def test_memory_reads_and_removes_this_chats_summary(self):
        core, _ = await self.core()
        self.assertIn("No summary of this chat yet", await self.say(core, "$memory", is_direct=True))
        HistoryHandle(core.manager, Address("chat", "room")).summarize("They planned a trip.", upto=1.0)
        self.assertIn("They planned a trip.", await self.say(core, "$memory", is_direct=True))
        self.assertIn("$memory clear", await self.say(core, "$memory forget 1", is_direct=True))
        self.assertIn("was removed", await self.say(core, "$memory clear", is_direct=True))
        self.assertIsNone(HistoryHandle(core.manager, Address("chat", "room")).summary())


if __name__ == "__main__":
    unittest.main()

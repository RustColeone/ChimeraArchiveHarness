"""tools/migrate.py on a data folder as the code before it left one: dry by default, each item once, copies first."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import mneme_llm

from core.manager.facts import slot
from core.manager.policy import Assignment
from core.manager.threads import Threads, thread_key
from core.storage.tank import SCHEMA, Tank
from plugins.webui.store import SCHEMA as WEB_SCHEMA, Store
from tests.core_support import ROOT

OLD_STUDENT = """
create table meta (key text primary key, value text not null);
insert into meta values ('schema_version', '1');
create table episodes (id integer primary key, space text not null, subject text not null, at real not null,
    conversation text not null default '', lines text not null, size integer not null, stability real not null,
    recalled_at real, recalls integer not null default 0, terms text);
insert into episodes (space, subject, at, conversation, lines, size, stability)
    values ('gpt', 'chat:alice', 1700000000.0, 'chat:dm', '[["Alice", "my teacher is Anna"], ["GPT", "Ok."]]', 1, 30.0);
"""
RUN = ("INSERT INTO runs(id,address,lane,engine,personas,assignment,status,origin,trigger,state,usage,created_at,"
       "updated_at) VALUES(?,?,?,?,?,?,?,'person','{}','{}','{}',1,1)")


def put(db, scope, key, value):
    db.execute("INSERT INTO kv(scope, key, value) VALUES(?, ?, ?)", (scope, key, json.dumps(value, ensure_ascii=False)))


def old_tank(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA.replace(", files TEXT", ""))
        for scope, key, value in (
                ("persona:gpt", "thread_since", 100.0),
                ("persona:gpt", "thread_since:chat:room", 110.0),
                ("persona:luna", "thread_since", 90.0),
                ("persona:gpt", "rotation", 3),
                ('extension:momochat {"conversation": "chat:room"}', "thread_since", 120.0),
                ('extension:momochat {"conversation": "chat:room"}', "rotation", 2),
                ("extension:room", "seen", 1),
                ('extension:assistant {"conversation": "chat:x"}', "compact_retry_at", 5.0),
                ('extension:companion {"persona": "luna"}', "mood", 7),
                ('extension:students {"persona": "gpt"}', "mood", 8),
                ("core:assignments", "webui:dm-gpt", {"pattern": "webui:dm-gpt", "engine": "room", "persona": "luna",
                                                      "allow": ["basic.*"], "deny": ["basic.notes"], "preapprove": [],
                                                      "since": 5.0}),
                ("core:assignments", "chat:plain", {"pattern": "chat:plain", "engine": "momochat", "personas": ["gpt"],
                                                    "allow": ["*"], "deny": []}),
                ("core:models", "chat:room", {"luna": "fake/old", "gpt": "fake/mine", "claude": "fake/hers"}),
                ("core:models", "chat:side", {"luna": "fake/side"}),
                ("core:facts", slot("luna"), {"companion.mood": 1}),
                ("core:facts", slot("gpt"), {"students.mood": 2}),
                ("core:facts", slot("whale_chan", ("chat", "alice")), {"companion.bond": {"role": "friend"}})):
            put(db, scope, key, value)
        old = {"pattern": "*", "engine": "assistant", "personas": ["luna"], "allow": ["*"], "deny": []}
        db.execute(RUN, ("open", "chat:room", "chat:room", "assistant", '["luna"]', json.dumps(old), "waiting_input"))
        db.execute(RUN, ("closed", "chat:room", "chat:room", "room", '["luna"]', json.dumps(old), "done"))
        db.execute("INSERT INTO messages(address,direction,sender_name,text,kind,at) "
                   "VALUES('chat:room','out','Luna','Hi.','text',1)")
        db.execute("INSERT INTO log(at,module,kind,text,address) VALUES(1,'core','note','Likes tea','chat:room')")
        db.execute("INSERT INTO log(at,module,kind,text,address) VALUES(1,'core','action','Did a thing','chat:room')")
        db.commit()


def old_web(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(WEB_SCHEMA)
        db.execute("INSERT INTO conversations(id,title,created_at,updated_at,position,personas) "
                   "VALUES('dm-gpt','Luna',1,1,1,?)", ('["luna"]',))
        db.execute("INSERT INTO conversations(id,title,created_at,updated_at,position) "
                   "VALUES('classroom','The club',1,1,0)")
        db.execute("INSERT INTO messages(conversation,at,item) VALUES('dm-gpt',1,?)",
                   (json.dumps({"kind": "text", "text": "Hi.", "speaker": "Luna"}),))
        db.commit()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "core"
        students = self.data / "extensions" / "students"
        web = self.data / "extensions" / "webui"
        room, assistant = self.data / "extensions" / "room", self.data / "extensions" / "assistant"
        for folder in (students, web, room, assistant):
            folder.mkdir(parents=True)
        (room / "room.json").write_text("{}", encoding="utf-8")
        (assistant / "assistant.json").write_text("{}", encoding="utf-8")
        old_tank(self.data / "tank.db")
        old_web(web / "webui.db")
        with closing(sqlite3.connect(students / "gpt.db")) as db:
            db.executescript(OLD_STUDENT)
        (students / "names.json").write_text('{"gpt": {"display_name": "GPT"}}', encoding="utf-8")
        lab = self.root / "workbench"
        worktree, git = lab / "worktrees" / "t1", self.root / "project.git" / "worktrees" / "t1"
        worktree.mkdir(parents=True)
        git.mkdir(parents=True)
        (worktree / ".git").write_text(f"gitdir: {git}\n", encoding="utf-8")
        (git / "workbench-base").write_text("abc\n", encoding="utf-8")
        with closing(sqlite3.connect(lab / "workbench.db")) as db:
            db.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, address TEXT NOT NULL)")
            db.execute("INSERT INTO tasks VALUES('t1', 'workbench:t1')")
            db.commit()

    def migrate(self, *options) -> str:
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "migrate.py"), str(self.data), *options], cwd=ROOT,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def snapshot(self) -> dict:
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*")
                if path.is_file() and not path.name.endswith(("-wal", "-shm"))}

    def kv(self, tank, scope):
        store = tank.store(scope)
        return {key: store.get(key) for key in store.keys()}

    def test_without_apply_it_says_what_it_would_do_and_changes_nothing(self):
        before = self.snapshot()
        said = self.migrate()
        self.assertEqual(self.snapshot(), before)
        for line in ("A dry run", "moves to", "schema 1 to 2", "thread starts moved", "notes dropped", "names.json",
                     "open runs", "becomes board.db", "becomes chimera-base"):
            self.assertIn(line, said)

    def test_it_does_every_item(self):
        said = self.migrate("--apply")
        tank = Tank(self.data / "tank.db")
        self.addCleanup(tank.close)
        threads = Threads(tank)
        self.assertEqual(self.kv(tank, "core:threads"), {
            thread_key("", "gpt"): 100.0, thread_key("chat:room", "gpt"): 110.0, thread_key("chat:room"): 120.0})
        self.assertEqual(threads.since("chat:room", ["gpt"]), 120.0)
        self.assertEqual(tank.store("persona:luna").keys(), [])
        self.assertEqual(self.kv(tank, "persona:gpt"), {"rotation": 3})  # (left, and said so)
        self.assertIn("1 other values stay", said)
        self.assertEqual(self.kv(tank, 'extension:momochat {"conversation": "chat:room"}'), {"rotation": 2})
        self.assertEqual(tank.store("extension:momochat").get("seen"), 1)
        self.assertEqual(tank.store('extension:momochat {"conversation": "chat:x"}').get("compact_retry_at"), 5.0)
        self.assertEqual(tank.store('extension:students {"persona": "gpt"}').get("mood"), 8)  # what she has wins
        self.assertEqual(self.kv(tank, "extension:room"), {})
        assignments = self.kv(tank, "core:assignments")
        self.assertEqual({key: value.get("allow") for key, value in assignments.items()},
                         {"webui:dm-gpt": None, "chat:plain": None})
        for pattern, value in assignments.items():
            Assignment.from_dict(value)
        self.assertEqual((assignments["webui:dm-gpt"]["engine"], assignments["webui:dm-gpt"]["personas"]),
                         ("momochat", ["gpt"]))
        self.assertIn("webui:dm-gpt", said)  # its allow and deny are the owner's to carry over
        self.assertNotIn("chat:plain (allow", said)
        self.assertEqual(self.kv(tank, "core:models"), {"chat:room": {"gpt": "fake/mine", "claude": "fake/hers"},
                                                        "chat:side": {"gpt": "fake/side"}})
        self.assertEqual(self.kv(tank, "core:facts"), {
            slot("gpt"): {"students.mood": 2},
            slot("deepseek", ("chat", "alice")): {"students.bond": {"role": "friend"}}})
        run = tank.run("open")
        self.assertEqual((run.engine, run.personas), ("momochat", ["gpt"]))
        Assignment.from_dict(run.assignment)
        self.assertEqual(tank.run("closed").engine, "room")  # (only what is still open is read)
        self.assertEqual([line.kind for line in tank.log_lines("chat:room")], ["action"])
        self.assertEqual([(item.sender_name, item.files) for item in tank.recent_messages("chat:room")], [("GPT", ())])
        store = Store(self.data / "extensions" / "webui" / "webui.db")
        self.addCleanup(store.close)
        self.assertEqual(store.conversation("dm-gpt")["personas"], ["gpt"])
        self.assertEqual(store.assigned(), ["dm-gpt"])
        self.assertEqual(store.messages("dm-gpt")[0]["speaker"], "GPT")
        students = self.data / "extensions" / "students"
        self.assertFalse((students / "names.json").exists())
        with closing(mneme_llm.Mneme(str(students / "gpt.db"), "gpt", embed=False, memory_language=None)) as memory:
            self.assertEqual(memory.surface.read("chat:alice").tokens > 0, True)
        self.assertTrue((self.data / "extensions" / "momochat" / "assistant.json").is_file())
        self.assertTrue((self.data / "extensions" / "room" / "room.json").is_file())  # both hold data: it stays
        self.assertIn("merge them by hand", said)
        lab = self.root / "chimera"
        self.assertFalse((self.root / "workbench").exists())
        self.assertFalse((lab / "workbench.db").exists())
        with closing(sqlite3.connect(lab / "board.db")) as db:
            self.assertEqual(db.execute("SELECT address FROM tasks").fetchall(), [("classroom:t1",)])
        base = self.root / "project.git" / "worktrees" / "t1"
        self.assertEqual([path.name for path in base.iterdir()], ["chimera-base"])

    def test_it_copies_each_file_before_it_changes_it(self):
        before = self.snapshot()
        self.migrate("--apply")
        with closing(sqlite3.connect(self.data / "tank.db.before-migrate")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM log").fetchone(), (2,))
        for path in ("extensions/webui/webui.db", "extensions/students/gpt.db"):
            self.assertTrue((self.data / (path + ".before-migrate")).is_file())
        self.assertEqual((self.data / "extensions" / "students" / "names.json.before-migrate").read_bytes(),
                         before["core/extensions/students/names.json"])

    def test_twice_is_once(self):
        self.migrate("--apply")
        before = self.snapshot()
        said = self.migrate("--apply")
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("moved", said.replace("nothing to do", ""))
        self.assertIn("tank.db: nothing to do", said)

    def test_a_web_page_from_before_its_columns_gets_them(self):
        path = self.data / "extensions" / "webui" / "webui.db"
        path.unlink()
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at REAL NOT NULL,"
                       " updated_at REAL NOT NULL)")
            db.execute("INSERT INTO conversations VALUES('classroom', 'The club', 1, 7)")
            db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL, "
                       "at REAL NOT NULL, approval TEXT, item TEXT NOT NULL)")
            db.commit()
        self.assertIn("ordered and pinned", self.migrate("--apply"))
        store = Store(path)
        self.addCleanup(store.close)
        chat = store.conversation("classroom")
        self.assertEqual((chat["position"], chat["pinned"], chat["personas"]), (-7, 0, None))
        self.assertEqual(store.assigned(), [])

    def test_a_folder_of_nothing_says_so(self):
        empty = self.root / "elsewhere" / "core"
        empty.mkdir(parents=True)
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "migrate.py"), str(empty)], capture_output=True,
                              text=True)
        self.assertIn("nothing here to migrate", done.stdout)


if __name__ == "__main__":
    unittest.main()

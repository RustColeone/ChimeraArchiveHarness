"""One migration, by hand, once: the data of before the clean-up of 2026-11, in the shape the code reads now.

    venv/bin/python tools/migrate.py data/core            # says what it would do; changes nothing
    venv/bin/python tools/migrate.py data/core --apply    # does it

Stop the bot first. The folder is the core's own (`data_dir`, with `tank.db` in it). Each file it changes is copied to
`<file>.before-migrate` first, and running it twice changes nothing the second time.

What it does: every student's memory file made current (`mneme_llm.migrate`); in the tank, when each thread began moves
to `core:threads`, assignments lose `allow` and `deny` (the patterns that used them are named: put them under
`permissions:` in core.yml), `kind="note"` lines go, and whatever is still under an old name of a persona, an engine or
a module takes the name of now (stores, `core:models`, `core:facts`, open runs, what she said); folders of old module
names move; `webui.db` gets the columns its schema has now, and `assigned` the chats this page gave an assignment of
their own; `names.json` goes; the Classroom's board and `data/workbench` take their names of now.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.manager.threads import THREADS, thread_key  # noqa: E402  (after the path)
from core.storage.tank import OPEN  # noqa: E402
from mneme_llm.migrate import migrate as make_current  # noqa: E402
from mneme_llm.store import SCHEMA_VERSION  # noqa: E402

PERSONAS = {"luna": "gpt", "whale_chan": "deepseek", "whale": "deepseek"}
SHOWN = {"gpt": "GPT", "deepseek": "DeepSeek"}
ENGINES = {"assistant": "momochat", "chat": "momochat", "room": "momochat", "workbench": "chimera"}
MODULES = {"assistant": "momochat", "room": "momochat", "companion": "students", "workbench": "chimera"}
OLD_ACCESS = ("allow", "deny", "preapprove")
BACKUP = ".before-migrate"
WHOLE_THREAD = "thread_since"
ONE_THREAD = re.compile(r"^thread_since:(.+)$")


class Report:
    """What was done, item by item."""

    def __init__(self, apply: bool):
        self.apply, self.lines = apply, []

    def say(self, item: str, what: str) -> None:
        self.lines.append(f"{item}: {what}")
        print(self.lines[-1], flush=True)


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def copy_database(source: Path, target: Path) -> None:
    """A whole copy, with what a stopped bot left in the write-ahead log."""
    with closing(sqlite3.connect(str(source))) as read, closing(sqlite3.connect(str(target))) as write:
        read.backup(write)


def table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def columns(db: sqlite3.Connection, name: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({name})")}


def changed(path: Path, change: Callable[[Path], list[str]], report: Report, item: str) -> None:
    """`change` on a copy first, which is all a dry run does; with `--apply`, then on the file, once it is backed up."""
    with tempfile.TemporaryDirectory() as folder:
        trial = Path(folder) / path.name
        copy_database(path, trial)
        lines = change(trial)
    if not lines:
        report.say(item, "nothing to do")
        return
    if report.apply:
        backup = path.with_name(path.name + BACKUP)
        if not backup.exists():
            copy_database(path, backup)
        change(path)
    for line in lines:
        report.say(item, line)


# ---- the tank ----------------------------------------------------------------------------------------------------
def scope_now(scope: str) -> str:
    """A store's scope under the names of now."""
    if scope.startswith("persona:"):
        name = scope.removeprefix("persona:")
        return "persona:" + PERSONAS.get(name, name)
    if not scope.startswith("extension:"):
        return scope
    module, _, parts = scope.removeprefix("extension:").partition(" ")
    if parts:
        try:
            scoped = json.loads(parts)
        except ValueError:
            scoped = None
        if isinstance(scoped, dict):
            if scoped.get("persona") in PERSONAS:
                scoped["persona"] = PERSONAS[scoped["persona"]]
            parts = json.dumps(scoped, ensure_ascii=False, sort_keys=True)
    return "extension:" + MODULES.get(module, module) + (" " + parts if parts else "")


def rename_scopes(db: sqlite3.Connection) -> int:
    """What is under an old scope moves to the one of now; what that one has already stays."""
    moved = 0
    for row in db.execute("SELECT DISTINCT scope FROM kv").fetchall():
        target = scope_now(row["scope"])
        if target != row["scope"]:
            db.execute("INSERT OR IGNORE INTO kv(scope, key, value) SELECT ?, key, value FROM kv WHERE scope=?",
                       (target, row["scope"]))
            moved += db.execute("DELETE FROM kv WHERE scope=?", (row["scope"],)).rowcount
    return moved


def start_thread(db: sqlite3.Connection, key: str, at) -> None:
    db.execute("INSERT INTO kv(scope, key, value) VALUES(?, ?, ?) ON CONFLICT(scope, key) DO UPDATE SET value="
               "MAX(CAST(value AS REAL), CAST(excluded.value AS REAL))", (THREADS, key, json.dumps(float(at))))


def move_threads(db: sqlite3.Connection) -> tuple[int, int]:
    """Thread keys to `core:threads`; returns how many moved, and what else is left in personas' stores."""
    moved = 0
    for row in db.execute("SELECT scope, key, value FROM kv WHERE scope LIKE 'persona:%'").fetchall():
        persona, one = row["scope"].removeprefix("persona:"), ONE_THREAD.match(row["key"])
        if row["key"] == WHOLE_THREAD or one:
            start_thread(db, thread_key(one.group(1) if one else "", persona), json.loads(row["value"]) or 0)
            db.execute("DELETE FROM kv WHERE scope=? AND key=?", (row["scope"], row["key"]))
            moved += 1
    for row in db.execute("SELECT scope, value FROM kv WHERE key=? AND scope LIKE 'extension:momochat {%'",
                          (WHOLE_THREAD,)).fetchall():
        address = json.loads(row["scope"].partition(" ")[2]).get("conversation")
        if address:
            start_thread(db, thread_key(address), json.loads(row["value"]) or 0)
            db.execute("DELETE FROM kv WHERE scope=? AND key=?", (row["scope"], WHOLE_THREAD))
            moved += 1
    left = db.execute("SELECT COUNT(*) AS n FROM kv WHERE scope LIKE 'persona:%'").fetchone()["n"]
    return moved, left


def assignment_now(value: dict) -> dict:
    """An assignment as `Assignment.from_config` takes it, under the names of now."""
    value = {key: item for key, item in value.items() if key not in OLD_ACCESS}
    if "persona" in value:
        named = value.pop("persona")
        value.setdefault("personas", [named] if named else [])
    if "personas" in value:
        value["personas"] = [PERSONAS.get(name, name) for name in value["personas"]]
    if "engine" in value:
        value["engine"] = ENGINES.get(value["engine"], value["engine"])
    return value


def fix_assignments(db: sqlite3.Connection) -> tuple[int, list[str]]:
    fixed, limited = 0, []
    for row in db.execute("SELECT key, value FROM kv WHERE scope='core:assignments'").fetchall():
        value = json.loads(row["value"])
        if list(value.get("allow") or ["*"]) != ["*"] or value.get("deny"):
            limited.append(f"{row['key']} (allow {value.get('allow')}, deny {value.get('deny')})")
        now = assignment_now(value)
        if now != value:
            db.execute("UPDATE kv SET value=? WHERE scope='core:assignments' AND key=?",
                       (json.dumps(now, ensure_ascii=False, sort_keys=True), row["key"]))
            fixed += 1
    return fixed, limited


def fix_model_choices(db: sqlite3.Connection) -> int:
    fixed = 0
    for row in db.execute("SELECT key, value FROM kv WHERE scope='core:models'").fetchall():
        value = json.loads(row["value"])
        if PERSONAS.keys() & value.keys():
            renamed = {PERSONAS[name]: choice for name, choice in value.items() if name in PERSONAS}
            kept = {name: choice for name, choice in value.items() if name not in PERSONAS}
            db.execute("UPDATE kv SET value=? WHERE scope='core:models' AND key=?",
                       (json.dumps({**renamed, **kept}, ensure_ascii=False, sort_keys=True), row["key"]))
            fixed += 1
    return fixed


def fix_facts(db: sqlite3.Connection) -> int:
    """Facts of an old persona or an old module; what is under the name of now wins."""
    fixed = 0
    for row in db.execute("SELECT key, value FROM kv WHERE scope='core:facts'").fetchall():
        slot, facts = json.loads(row["key"]), json.loads(row["value"])
        named = [PERSONAS.get(slot[0], slot[0]), *slot[1:]]
        renamed = {f"{MODULES.get(name.partition('.')[0], name.partition('.')[0])}.{name.partition('.')[2]}": value
                   for name, value in facts.items()}
        if named == slot and renamed == facts:
            continue
        target = json.dumps(named, ensure_ascii=False)
        there = db.execute("SELECT value FROM kv WHERE scope='core:facts' AND key=?", (target,)).fetchone()
        merged = {**renamed, **(json.loads(there["value"]) if there and target != row["key"] else {})}
        db.execute("DELETE FROM kv WHERE scope='core:facts' AND key=?", (row["key"],))
        db.execute("INSERT OR REPLACE INTO kv(scope, key, value) VALUES('core:facts', ?, ?)",
                   (target, json.dumps(merged, ensure_ascii=False, sort_keys=True)))
        fixed += 1
    return fixed


def fix_open_runs(db: sqlite3.Connection) -> int:
    fixed = 0
    marks = ",".join("?" for _ in OPEN)
    for row in db.execute(f"SELECT id, engine, personas, assignment FROM runs WHERE status IN ({marks})",
                          OPEN).fetchall():
        engine = ENGINES.get(row["engine"], row["engine"])
        personas = [PERSONAS.get(name, name) for name in json.loads(row["personas"])]
        assignment = assignment_now(json.loads(row["assignment"]))
        if engine != row["engine"] or personas != json.loads(row["personas"]) \
                or assignment != json.loads(row["assignment"]):
            db.execute("UPDATE runs SET engine=?, personas=?, assignment=? WHERE id=?",
                       (engine, json.dumps(personas, ensure_ascii=False), json.dumps(assignment, ensure_ascii=False,
                                                                                    sort_keys=True), row["id"]))
            fixed += 1
    return fixed


def tank(path: Path) -> list[str]:
    done: list[str] = []

    def said(count: int, what: str) -> None:
        if count:
            done.append(f"{count} {what}")

    with closing(connect(path)) as db:
        db.execute("BEGIN IMMEDIATE")
        if "files" not in columns(db, "messages"):
            db.execute("ALTER TABLE messages ADD COLUMN files TEXT")
            done.append("messages can hold files")
        if table(db, "diary"):
            lines = db.execute("SELECT COUNT(*) AS n FROM diary").fetchone()["n"]
            db.execute("DROP TABLE diary")
            done.append(f"the old diary is gone ({lines} lines)")
        if table(db, "log"):
            said(db.execute("DELETE FROM log WHERE kind='note'").rowcount,
                 "notes dropped from the log (nothing writes them)")
            for old, new in PERSONAS.items():
                said(db.execute("UPDATE log SET persona=? WHERE persona=?", (new, old)).rowcount,
                     f"log lines of {old} are {new}'s")
        said(rename_scopes(db), "stored values moved to the names of now")
        moved, left = move_threads(db)
        said(moved, "thread starts moved to core:threads")
        if moved and left:
            done.append(f"{left} other values stay in personas' stores (nothing reads them)")
        fixed, limited = fix_assignments(db)
        said(fixed, "runtime assignments cleaned")
        for item in limited:
            done.append(f"assignment {item} limited what ran there: say so under `permissions:` in core.yml")
        said(fix_model_choices(db), "model choices moved to the names of now")
        said(fix_facts(db), "facts moved to the names of now")
        said(fix_open_runs(db), "open runs moved to the names of now")
        for old, new in PERSONAS.items():
            said(db.execute("UPDATE messages SET sender_name=? WHERE direction='out' AND lower(sender_name)=lower(?)",
                            (SHOWN[new], old)).rowcount, f"messages of {old} are {SHOWN[new]}'s")
        db.execute("COMMIT")
    return done


# ---- the web UI --------------------------------------------------------------------------------------------------
def web_chats(assignments: dict[str, dict]) -> Callable[[Path], list[str]]:
    """`assignments`: the runtime ones by pattern, for the chats this page gave one of their own."""
    def change(path: Path) -> list[str]:
        done = []
        with closing(connect(path)) as db:
            db.execute("BEGIN IMMEDIATE")
            have = columns(db, "conversations")
            if "position" not in have:
                db.execute("ALTER TABLE conversations ADD COLUMN position REAL")
                db.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
                db.execute("UPDATE conversations SET position = -updated_at")
                done.append("chats can be ordered and pinned")
            if "personas" not in have:
                db.execute("ALTER TABLE conversations ADD COLUMN personas TEXT")
                done.append("chats can name who is in them")
            db.execute("CREATE TABLE IF NOT EXISTS assigned (conversation TEXT PRIMARY KEY, at REAL NOT NULL)")
            renamed = marked = spoken = 0
            for row in db.execute("SELECT id, personas FROM conversations WHERE personas IS NOT NULL").fetchall():
                personas = json.loads(row["personas"])
                now = list(dict.fromkeys(PERSONAS.get(name, name) for name in personas))
                if now != personas:
                    db.execute("UPDATE conversations SET personas=? WHERE id=?", (json.dumps(now), row["id"]))
                    renamed += 1
                if f"webui:{row['id']}" in assignments and db.execute(
                        "INSERT OR IGNORE INTO assigned(conversation, at) VALUES(?, 0)", (row["id"],)).rowcount:
                    marked += 1
            for old, new in PERSONAS.items():
                for row in db.execute("SELECT id, item FROM messages WHERE item LIKE ?", (f"%{old}%",)).fetchall():
                    item = json.loads(row["item"])
                    if str(item.get("speaker") or "").casefold() == old:
                        item["speaker"] = SHOWN[new]
                        db.execute("UPDATE messages SET item=? WHERE id=?",
                                   (json.dumps(item, ensure_ascii=False), row["id"]))
                        spoken += 1
            done += [line for line in (f"{renamed} chats name the students of now" if renamed else "",
                                       f"{marked} chats' assignments are this page's" if marked else "",
                                       f"{spoken} bubbles speak under the names of now" if spoken else "") if line]
            db.execute("COMMIT")
        return done
    return change


# ---- the Classroom -----------------------------------------------------------------------------------------------
def board(path: Path) -> list[str]:
    with closing(connect(path)) as db:
        count = db.execute("UPDATE tasks SET address = 'classroom:' || substr(address, 11) WHERE address LIKE "
                           "'workbench:%'").rowcount
    return [f"{count} tasks are the classroom's"] if count else []


def classroom(folder: Path, report: Report) -> None:
    """The board's file, its tasks' addresses and each worktree's base, in one Classroom folder."""
    old, new = folder / "workbench.db", folder / "board.db"
    if old.exists() and not new.exists():
        report.say(str(old), f"becomes {new.name}")
        if report.apply:
            copy_database(old, old.with_name(old.name + BACKUP))
            copy_database(old, new)
            for path in (old, *(old.with_name(old.name + end) for end in ("-wal", "-shm"))):
                path.unlink(missing_ok=True)
    named = new if new.exists() else old
    if named.exists():
        changed(named, board, report, str(named))
    for mark in (folder / "worktrees").glob("*/.git"):
        found = re.match(r"gitdir: (.+)", mark.read_text(encoding="utf-8")) if mark.is_file() else None
        base = Path(found.group(1).strip()) / "workbench-base" if found else None
        if base is not None and base.is_file():
            report.say(str(base), "becomes chimera-base")
            if report.apply:
                base.rename(base.with_name("chimera-base"))


# ---- the rest ----------------------------------------------------------------------------------------------------
def move_folder(old: Path, new: Path, report: Report) -> None:
    """A folder under an old name becomes the one of now, when that has nothing yet; else both stay and it says so."""
    if not old.is_dir():
        return
    if new.is_dir() and any(new.iterdir()):
        report.say(str(old), f"left as it is: {new} holds data too (merge them by hand)")
        return
    report.say(str(old), f"moves to {new}")
    if report.apply:
        if new.is_dir():
            new.rmdir()
        shutil.move(str(old), str(new))


def student_files(folder: Path, report: Report) -> None:
    def change(path: Path) -> list[str]:
        with closing(connect(path)) as db:
            row = table(db, "meta") and db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not row or int(row["value"]) == SCHEMA_VERSION:
            return []
        return [make_current(path).partition(": ")[2]]

    for path in sorted(folder.glob("*.db")):
        try:
            changed(path, change, report, str(path))
        except (ValueError, sqlite3.Error) as error:
            report.say(str(path), f"left as it is: {error}")
    for old in PERSONAS:
        if (folder / f"{old}.db").is_file():
            report.say(str(folder / f"{old}.db"), f"left as it is: no student reads it ({old} is {PERSONAS[old]} now)")
    names = folder / "names.json"
    if names.is_file():
        report.say(str(names), "removed (their names come from the students' folders)")
        if report.apply:
            shutil.copy2(names, names.with_name(names.name + BACKUP))
            names.unlink()


def runtime_assignments(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with closing(connect(path)) as db:
        return {row["key"]: json.loads(row["value"]) for row in
                db.execute("SELECT key, value FROM kv WHERE scope='core:assignments'")} if table(db, "kv") else {}


def migrate(data: Path, apply: bool) -> Report:
    report = Report(apply)
    extensions = data / "extensions"
    for old, new in MODULES.items():
        move_folder(extensions / old, extensions / new, report)
    move_folder(data.parent / "workbench", data.parent / "chimera", report)

    def there(name: str) -> Path:
        """A module's folder (on a dry run it may still be under an old name)."""
        return next((folder for folder in (extensions / name, *(extensions / old for old, new in MODULES.items()
                                                                if new == name)) if folder.is_dir()), extensions / name)

    students = there("students")
    if students.is_dir():
        student_files(students, report)
    tank_file = data / "tank.db"
    if tank_file.is_file():
        changed(tank_file, tank, report, str(tank_file))
    web = extensions / "webui" / "webui.db"
    if web.is_file():
        changed(web, web_chats(runtime_assignments(tank_file)), report, str(web))
    for folder in {there("chimera"), data.parent / "chimera", data.parent / "workbench"}:
        if folder.is_dir():
            classroom(folder, report)
    if not report.lines:
        report.say(str(data), "nothing here to migrate")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", type=Path, help="the core's data folder (data/core, with tank.db in it)")
    parser.add_argument("--apply", action="store_true", help="do it (without it, it only says what it would do)")
    arguments = parser.parse_args(argv)
    if not arguments.data.is_dir():
        parser.error(f"{arguments.data} is not a folder")
    print("Applying." if arguments.apply else "A dry run: nothing changes. --apply does it.", flush=True)
    migrate(arguments.data.resolve(), arguments.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())

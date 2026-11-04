"""Build the lessons a student is born with: her gut's starter, from her own character.

    python tools/gut_starter.py deepseek                       # writes extensions/students/deepseek/gut-starter.json.gz

Everyday chats in four languages, at three closenesses, already read into forms (extensions/students/shared/
gut-readings.json.gz, 2,400 messages, of which `--every` keeps one in so many), with the moments everyday chat lacks
mixed in (gut-readings-more.json.gz, from tools/gut_more.py: fear, blame, mockery, a rival, praise, shame, quiet, a long
talk, an apology, being let down), go to her real character, so students differ by character alone. She answers each,
then writes her note as she does in a real chat; the form and that note are a lesson, and the words she uses say what
is normal for her. Only her replies and notes cost anything. Her birth is a lean: her prompt gives the rest. It stops by itself at --floor CNY of DeepSeek balance; the key is DEEPSEEK_API_KEY,
from the environment or the .env file named by --env-file (only that key is read from it). Other students: --base-url,
--model and --key-env name an OpenAI-compatible endpoint.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TELL = {20: "\n\n(This person is someone you know; you are not close yet.)",  # (the app's own sentences)
        50: "\n\n(This person is your friend; you are on friendly terms.)",
        85: "\n\n(This person is family to you; you are very close.)"}
SPEAK = {"zh": "\n\nReply in Mandarin Chinese.", "yue": "\n\nReply in written Cantonese.", "en": "\n\nReply in English.",
         "ja": "\n\nReply in Japanese."}
HISTORY = 16


def key_from(name: str, env_file: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    for line in Path(env_file).read_text().splitlines():
        found, _, value = line.partition("=")
        if found.strip() == name:
            return value.strip().strip("\"'")
    raise SystemExit(f"{name} is not set")


def balance(key: str) -> float:
    request = urllib.request.Request("https://api.deepseek.com/user/balance", headers={"Authorization": f"Bearer {key}"})
    infos = json.load(urllib.request.urlopen(request, timeout=20))["balance_infos"]
    return float(next(item["total_balance"] for item in infos if item["currency"] == "CNY"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a student's gut starter from her character.")
    parser.add_argument("student")
    parser.add_argument("--env-file", default=str(ROOT.parent / ".env"))
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--floor", type=float, default=30.0, help="stop at this DeepSeek balance, CNY")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--every", type=int, default=3, help="keep one everyday message in so many")
    parser.add_argument("--more", default=str(ROOT / "extensions/students/shared/gut-readings-more.json.gz"),
                        help="the extra moments (tools/gut_more.py); '' for none")
    arguments = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from openai import OpenAI
    from extensions.students.extension import read_students
    from mneme_llm.gut import ENDS, mine, note_messages, written
    student = next((data for data in read_students() if data["name"] == arguments.student), None)
    if student is None:
        raise SystemExit(f"no student called {arguments.student}")
    key = key_from(arguments.key_env, arguments.env_file)
    client = OpenAI(api_key=key, base_url=arguments.base_url)
    with gzip.open(ROOT / "extensions/students/shared/gut-readings.json.gz", "rt", encoding="utf-8") as file:
        chats = json.load(file)
    for index, chat in enumerate(chats):  # one in so many, a different one in each chat
        chat["items"] = chat["items"][index % arguments.every::arguments.every]
    if arguments.more and Path(arguments.more).exists():
        with gzip.open(arguments.more, "rt", encoding="utf-8") as file:
            more = json.load(file)
        for language in {chat["language"] for chat in chats}:  # each extra moment into a chat of its language
            mine_chats = [chat for chat in chats if chat["language"] == language]
            extra = [item for item in more if item["language"] == language]
            for number, item in enumerate(extra):
                chat = mine_chats[number % len(mine_chats)]
                at = (number // len(mine_chats) * 3 + 1) % (len(chat["items"]) + 1)
                chat["items"].insert(at, {"said": item["said"], "form": item["form"]})
    spent_from = balance(key) if "deepseek" in arguments.base_url else None
    stopped = []

    def run(chat: dict) -> list[dict]:
        system = student["prompt"] + TELL[chat["closeness"]] + SPEAK[chat["language"]]
        history, rows = [], []

        def complete(messages: list[dict], tokens: int) -> str:
            for attempt in range(5):
                try:
                    return client.chat.completions.create(model=arguments.model, messages=messages, max_tokens=tokens,
                                                          timeout=90, reasoning_effort="none").choices[0].message.content or ""
                except Exception:
                    time.sleep(3 + 4 * attempt)
            return ""

        for item in chat["items"]:
            if stopped:
                break
            before = history[-HISTORY:]
            reply = complete([{"role": "system", "content": system}, *before, {"role": "user", "content": item["said"]}], 400)
            if not reply:
                continue
            note = written(complete(note_messages(system, "", before, item["said"], reply), 120))
            history += [{"role": "user", "content": item["said"]}, {"role": "assistant", "content": reply}]
            if note:
                rows.append({"language": chat["language"], "form": item["form"], "feel": note["feel"], "mood": note["mood"],
                             "closeness": chat["closeness"], "words": mine(item["said"], reply, chat["language"])})
        return rows

    rows = []
    with ThreadPoolExecutor(arguments.workers) as workers:
        for done, found in enumerate(workers.map(run, chats)):
            rows += found
            if done % 20 == 19:
                left = balance(key) if spent_from is not None else None
                print(f"{done + 1}/{len(chats)} chats, {len(rows)} lessons", f"balance {left}" if left else "", flush=True)
                if left is not None and left <= arguments.floor:
                    stopped.append(True)
    if stopped:
        print("stopped at the floor: nothing written")
        return 1
    words: dict[str, Counter] = {}
    replies: Counter = Counter()
    for row in rows:
        words.setdefault(row["language"], Counter()).update(row["words"])
        replies[row["language"]] += 1
    data = {"ends": list(ENDS), "rows": [[row["form"], row["feel"], row["mood"], row["closeness"]] for row in rows],
            "words": {language: {"n": replies[language], "words": {word: count for word, count in found.items() if count > 1}}
                      for language, found in words.items()}}
    path = ROOT / "extensions/students" / student["name"] / "gut-starter.json.gz"
    with gzip.GzipFile(path, "wb", mtime=0) as file:
        file.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
    print(f"{path}: {len(rows)} lessons of {sum(len(chat['items']) for chat in chats)}, {path.stat().st_size // 1024} KB",
          dict(Counter(max(row["feel"], key=row["feel"].get) for row in rows).most_common()),
          f"spent {round(spent_from - balance(key), 2)} CNY" if spent_from is not None else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())

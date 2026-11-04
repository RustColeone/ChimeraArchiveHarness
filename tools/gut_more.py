"""More moments for a student's birth: the kinds of message the everyday set lacks, so her gut is born knowing what
pushing back is like (fear, being blamed or mocked, a rival's teasing, praise and shame, wanting quiet or a long talk,
an apology, being let down). Her model writes the messages and reads each into a form, once, for every student.

    python tools/gut_more.py                 # writes extensions/students/shared/gut-readings-more.json.gz

Only DEEPSEEK_API_KEY is read, from the environment or the .env file named by --env-file. It stops by itself at --floor
CNY of balance.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from gut_starter import balance, key_from  # noqa: E402

KINDS = {
    "scary": "something frightening or dangerous is happening to them or near them right now",
    "blame": "they are angry at her and blame her for something she said or did",
    "mock": "they mock her or insult her, rudely",
    "rival": "competitive teasing: they boast that they are better than her at something, or dare her",
    "praise": "they praise something she did, or how clever or kind she is",
    "shame": "they point out a mistake she made, or something embarrassing about her",
    "quiet": "they want to be left alone for a while, or ask her to talk less",
    "chatty": "they invite her to talk at length: tell them everything about her day, or a long story",
    "sorry": "they apologise to her after an argument",
    "letdown": "they are hurt because she forgot something important or let them down",
}
LANGUAGES = {"zh": "Mandarin Chinese", "yue": "written Cantonese", "en": "English", "ja": "Japanese"}
WRITE = ("Write {n} short chat messages, in {language}, that a person might send to an AI companion they know well. "
         "In each, {kind}. Make them different: different situations, from a few words to two sentences, casual, the "
         "way people really type. One message per line, no numbering, no quotes, nothing else.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the extra moments for a student's birth.")
    parser.add_argument("--env-file", default=str(ROOT.parent / ".env"))
    parser.add_argument("--each", type=int, default=8, help="messages for each kind and language")
    parser.add_argument("--floor", type=float, default=3.0, help="stop at this DeepSeek balance, CNY")
    parser.add_argument("--out", default=str(ROOT / "extensions/students/shared/gut-readings-more.json.gz"))
    arguments = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from openai import OpenAI
    from mneme_llm.gut import json_in, reading_messages
    key = key_from("DEEPSEEK_API_KEY", arguments.env_file)
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    start = balance(key)
    if start <= arguments.floor:
        print(f"balance {start} is at the floor: nothing done")
        return 1

    def complete(messages: list[dict], tokens: int) -> str:
        for attempt in range(5):
            try:
                return client.chat.completions.create(model="deepseek-flash", messages=messages, max_tokens=tokens,
                                                      timeout=90, reasoning_effort="none").choices[0].message.content or ""
            except Exception:
                time.sleep(3 + 4 * attempt)
        return ""

    def written(job: tuple[str, str]) -> list[dict]:
        language, kind = job
        text = complete([{"role": "user", "content": WRITE.format(n=arguments.each, language=LANGUAGES[language],
                                                                 kind=KINDS[kind])}], 900)
        said = [line.strip().strip('"“”「」').strip() for line in text.splitlines() if line.strip()][:arguments.each]
        return [{"language": language, "kind": kind, "said": line} for line in said if line]

    def read(item: dict) -> dict | None:
        form = json_in(complete(reading_messages(item["said"]), 300))
        return {**item, "form": form} if form else None

    with ThreadPoolExecutor(8) as workers:
        items = [item for found in workers.map(written, [(language, kind) for language in LANGUAGES for kind in KINDS])
                 for item in found]
        print(len(items), "messages written; balance", balance(key), flush=True)
        read_items = [item for item in workers.map(read, items) if item]
    out = Path(arguments.out)
    with gzip.GzipFile(out, "wb", mtime=0) as file:
        file.write(json.dumps(read_items, ensure_ascii=False, separators=(",", ":")).encode())
    print(f"{out}: {len(read_items)} read of {len(items)}; spent {round(start - balance(key), 2)} CNY")
    return 0


if __name__ == "__main__":
    sys.exit(main())

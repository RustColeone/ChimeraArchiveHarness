"""A student's settings and her gut on her page, for the owner only, as the dsh-mneme-llm panel has them
(plugin/panel.js): her settings in four tabs, Her · People · Memory · Gut (`settings`, and `settle` for a save), drawn
by its page (page/settings.js, copied to the webui's static/mneme-settings.js); and her gut (`view`, `starmap`, and the
change it makes, `change`).

The page reads her view `students.settings` and saves with `$settings <student> <save>`, a save as JSON:

    {her: {name, language, zone, card: {text, on} | null}, me: {name, link, unlink},
     people: [{subject, role, closeness, hold, tune, weight, locked, forget}], others, memory: {surface_days, ...},
     rows: {learn, ...}, gut: <a change, as below, without people>}

any of them, or {start} alone; checked whole before any of it lands. Her name is used from the next start; everything
else at once.

The page reads her views `students.gut` and `students.starmap` (contracts.View: worked out when asked, never stored)
and changes her with `$tune <student> <change>`, a change as JSON:

    {tau, sensitivity, age, locked, tune: [{end, now, nature}],
     people: [{subject, tune: [{end, nature}], weight, locked, closeness, hold, forget}],
     sides: [{name, what, weight, drop}], side: {name, often} | null}

any of them, checked whole before any of it lands, so it lands whole or not at all. Her gut keeps it in its file
(`configure`, `set_age`, `tune`, `tune_person`, `write_side`, `drop_side`, `lock_side`, `unlock_side`, `forget`);
closeness and its lock go to her memory (`Relations.set`, `lock`, `unlock`).
"""

from __future__ import annotations

import math
import re

import mneme_llm.gut as G
from mneme_llm.config import check


def stamp(gut) -> str:
    """What changes her star map: a lesson, a sleep, her age set by hand, someone forgotten."""
    net = gut.net
    return f"{net.lessons}:{len(net.waiting)}:{round(net.age, 6)}:{len(net.people)}"


def closeness_of(memory) -> dict:
    """Who has a role in her memory, with the band of that role and whether closeness is locked."""
    if memory is None:
        return {}
    relations = memory.relations
    locks = relations.locks()
    found = {}
    for item in relations.all():
        kind = relations.roles.get(item.role)
        found[item.subject] = {"role": item.role, "value": round(item.closeness, 2),
                               "floor": kind.floor if kind else 0, "ceiling": kind.ceiling if kind else 100,
                               "locked": item.subject in locks}
    return found


def view(gut, you: str = "", memory=None, shown: dict | None = None) -> dict:
    """Her gut as the page shows it: her report, each bar lately against usual (the strength of its second end less its
    first), each end as she is tuned, each person she knows (how she is with them by hand, their closeness from her
    memory, and what the page calls them: `shown`, subject → name), and her sides. `you`: the subject of whoever reads."""
    report, close, shown = gut.report(), closeness_of(memory), shown or {}
    with gut.lock:
        settings, tone, net = gut.settings, gut.tone, gut.net
        subjects = list(dict.fromkeys([*net.people, *settings["people"], *close]))
        people = []
        for subject in subjects:
            found, hand = net.people.get(subject), settings["people"].get(subject) or {}
            people.append({"subject": subject, "name": shown.get(subject, ""), "you": subject == you,
                           "lessons": round(found["n"]) if found else 0, "weight": round(net.weight(subject), 3),
                           "nudge": dict(hand.get("nudge") or {}), "set": hand.get("weight"),
                           "locked": bool(hand.get("locked")), "closeness": close.get(subject)})
        hers = {**gut.tags, **gut.grown}
        sides = [{"name": name, "what": what, "given": name in gut.tags, "own": gut.weights.get(name, 0.0),
                  "weight": round(gut.weight(name), 1)} for name, what in hers.items()]
        ends = [{"end": end, "zh": G.CHINESE[end], "now": round(tone.shift.get(end, 0.0), 4),
                 "nature": settings["nudge"].get(end, 0.0)} for end in G.ENDS]
        bars = [{"bar": bar, "zh": zh, "ends": [left[0] if left else None, right[0]],
                 "lately": round(tone.level(bar), 3), "usual": round(tone.level(bar, "usual"), 3)}
                for bar, zh, left, right in G.BARS]
        side = dict(settings["side"]) if settings["side"] else None
        locked, names, the_stamp = settings["locked"], list(gut.names), stamp(gut)
    people.sort(key=lambda item: (not item["you"], -item["lessons"], item["subject"]))
    return {"stamp": the_stamp, "report": report, "locked": locked, "people": people, "sides": sides, "side": side,
            "names": names, "bars": bars, "ends": ends, "nature": G.NATURE, "grows": G.GROWS}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _within(value, low, high, what: str):
    if not _number(value) or not low <= value <= high:
        raise ValueError(f"{what} is a number from {low:g} to {high:g}")
    return value


def _list(value) -> list:
    return [] if value is None else value if isinstance(value, list) else [value]


def change(gut, asked, memory=None) -> None:
    """One change from her page, checked whole before any of it lands (see this module's docstring)."""
    prepare(gut, asked, memory)()


def prepare(gut, asked, memory=None):
    """`change` checked, and the work that makes it, for a caller that checks more before any of it lands."""
    if not isinstance(asked, dict):
        raise ValueError("a change is an object: tau, sensitivity, age, locked, tune, people, sides or side")
    tau, sensitivity, age, locked = (asked.get(key) for key in ("tau", "sensitivity", "age", "locked"))
    if tau is not None and not (_number(tau) and tau > 0):
        raise ValueError("tau is a number of lessons above 0")
    if sensitivity is not None:
        _within(sensitivity, -1, 1, "sensitivity")
    if age is not None and not (_number(age) and age >= 0):
        raise ValueError("an age is a number of lessons, 0 or more")
    if locked is not None and not isinstance(locked, bool):
        raise ValueError("locked is true or false")
    tunes = _list(asked.get("tune"))
    for tune in tunes:
        if not isinstance(tune, dict) or tune.get("end") not in G.ENDS:
            raise ValueError(f"not an end of hers: {tune.get('end') if isinstance(tune, dict) else tune}")
        if tune.get("now") is not None:
            _within(tune["now"], -1, 1, f"now for {tune['end']}")
        if tune.get("nature") is not None:
            _within(tune["nature"], -G.NATURE, G.NATURE, f"nature for {tune['end']}")
    close, people = closeness_of(memory), _list(asked.get("people"))
    for person in people:
        if not isinstance(person, dict) or not isinstance(person.get("subject"), str) or not person["subject"].strip():
            raise ValueError("a person is {subject, ...}")
        for tune in _list(person.get("tune")):
            if not isinstance(tune, dict) or tune.get("end") not in G.ENDS:
                raise ValueError(f"not an end of hers: {tune.get('end') if isinstance(tune, dict) else tune}")
            _within(tune.get("nature"), -G.NATURE, G.NATURE, f"nature for {tune['end']} with {person['subject']}")
        if person.get("weight") is not None and person["weight"] != "learned":
            _within(person["weight"], 0, 1, "weight")
        for key in ("locked", "hold", "forget"):
            if person.get(key) is not None and not isinstance(person[key], bool):
                raise ValueError(f"{key} is true or false")
        if person.get("closeness") is not None or person.get("hold") is not None:
            found = close.get(person["subject"])
            if found is None:
                raise ValueError(f"{person['subject']} has no role: closeness needs one")
            if person.get("closeness") is not None:
                _within(person["closeness"], found["floor"], found["ceiling"], f"closeness for {found['role']}")
    sides, written = _list(asked.get("sides")), set()
    for item in sides:
        if not isinstance(item, dict) or item.get("name") not in gut.names:
            raise ValueError(f"not a side she can have: {item.get('name') if isinstance(item, dict) else item}")
        what = item.get("what")
        if what is not None and (not isinstance(what, str) or not what.strip() or len(what) > 200):
            raise ValueError("a sentence is some words, at most 200 characters")
        if item.get("weight") is not None and not (_number(item["weight"]) and item["weight"] >= 0):
            raise ValueError("a weight is a number, 0 or more")
        if not item.get("drop") and what is None and item["name"] not in gut.grown:
            raise ValueError(f"{item['name']} is not one of her sides yet: give it a sentence")
        if what is not None:
            written.add(item["name"])
    side = asked.get("side", ...)
    if side is not ... and side is not None:
        if not isinstance(side, dict) or side.get("name") not in gut.names:
            raise ValueError(f"not a side she can have: {side.get('name') if isinstance(side, dict) else side}")
        _within(side.get("often", 1), 0, 1, "often")
        if side["name"] not in gut.tags and side["name"] not in gut.grown and side["name"] not in written:
            raise ValueError(f"{side['name']} is not one of her sides yet: give it a sentence")
    # all of it checked: what makes it
    def land() -> None:
        if tau is not None or sensitivity is not None or locked is not None:
            gut.configure(tau=tau, sensitivity=sensitivity, locked=locked)
        if age is not None:
            gut.set_age(age)
        for tune in tunes:
            gut.tune(tune["end"], now=tune.get("now"), nature=tune.get("nature"))
        for item in sides:
            if item.get("drop"):
                gut.drop_side(item["name"])
            else:
                gut.write_side(item["name"], item["what"] if item.get("what") is not None else gut.grown[item["name"]],
                               item["weight"] if item.get("weight") is not None
                               else gut.weights.get(item["name"], G.GROWS))
        if side is None:
            gut.unlock_side()
        elif side is not ...:
            gut.lock_side(side["name"], often=side.get("often", 1))
        for person in people:
            subject = person["subject"]
            if person.get("forget"):
                gut.forget(subject)
                continue
            for tune in _list(person.get("tune")):
                gut.tune_person(subject, tune["end"], tune["nature"])
            if person.get("weight") is not None or person.get("locked") is not None:
                gut.tune_person(subject, weight=person.get("weight"), locked=person.get("locked"))
            if memory is not None and (person.get("closeness") is not None or person.get("hold") is not None):
                relations, found = memory.relations, close[subject]
                if person.get("hold") is False:
                    relations.unlock(subject)
                holding = person["hold"] if person.get("hold") is not None else found["locked"]
                if holding:
                    relations.lock(subject, person.get("closeness"))
                elif person.get("closeness") is not None:
                    relations.set(subject, found["role"], closeness=person["closeness"])
    return land


# ---- the page's four tabs: Her · People · Memory · Gut ----------------------------------------------------------------

# The language she answers in, by the name the page shows: auto (each person's own) or one of these.
LANGUAGES = {"auto": "", "english": "en", "chinese": "zh", "cantonese": "yue", "japanese": "ja"}
NAMED = {"en": "english", "zh": "chinese", "mandarin": "chinese", "yue": "cantonese", "ja": "japanese"}
# What the Memory tab sets: how much the surface keeps, and the look of what was said (`said_budget` is the app's `said`).
MEMORY = ("surface_days", "surface_floor", "surface_cap", "surface_window", "said_budget", "said_words")
STARTS = ("fresh", "deep", "gut")  # what `$new` does: what she keeps of lately; and of everyone; and her gut
PARTS = ("her", "me", "people", "others", "memory", "rows", "gut", "start")
ACCOUNT = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,31}:\S{1,200}")  # an account as the files keep it: discord:42
GUT_ONLY = ("tune", "weight", "locked", "forget")  # of a person, what lives in her gut
LONGEST = 80  # characters of her name
CALLED = 40  # and of yours (as `$callme` takes it)
SAID = 50_000  # the look's characters at most (memory.py `said`)


def language_name(language) -> str:
    """A language as the page names it, from a setting (a name or a code; "" or none: auto)."""
    said = str(language or "").strip().lower()
    if not said or said == "auto":
        return "auto"
    if said in LANGUAGES:
        return said
    if said not in NAMED:
        raise ValueError("a language is auto, english, chinese, cantonese or japanese")
    return NAMED[said]


def spoken(language) -> str:
    """The code of the language she answers in ("": each person's own)."""
    return LANGUAGES[language_name(language)]


def written(language) -> str:
    """The language her memory's own sentences are in, for the one she answers in ("" for auto): Cantonese reads
    Chinese."""
    code = spoken(language)
    return "zh" if code == "yue" else code


def people_of(memory, gut, gut_view, you: str, names: dict) -> list:
    """Everyone the People tab lists: you first, then whoever has a role in her memory or taught her gut, the most
    taught first. Each with what the app calls them, their role and closeness (her memory) and how she is with them
    (her gut), where there is one."""
    close, taught = closeness_of(memory), {item["subject"]: item for item in (gut_view or {}).get("people", [])}
    subjects = list(dict.fromkeys([you, *taught, *close]))
    found = []
    for subject in subjects:
        item = taught.get(subject)
        found.append({"subject": subject, "you": subject == you, "name": names.get(subject, ""),
                      "role": (close.get(subject) or {}).get("role", ""), "closeness": close.get(subject),
                      "gut": {key: item[key] for key in ("lessons", "weight", "nudge", "set", "locked")} if item
                      else ({"lessons": 0, "weight": 0, "nudge": {}, "set": None, "locked": False} if gut is not None
                            else None)})
    found.sort(key=lambda item: (not item["you"], -((item["gut"] or {}).get("lessons") or 0), item["subject"]))
    return found


def settings(page) -> dict:
    """Every setting the page shows, for one student and the owner reading (`page`, memory.py's `Page`): her name, the
    language she answers in, her zone and Character Card (Her); you, your accounts, the role of people she meets and
    everyone she knows (People); the surface's size and the look (Memory); her gut, when she has one (Gut); and the
    app's own settings for her (`rows`, each on a tab, with its words)."""
    memory, gut, you = page.memory, page.gut, page.you
    gut_view = view(gut, you, memory, page.names) if gut is not None else None
    roles = [{"key": role.key, "floor": role.floor, "ceiling": role.ceiling, "start": role.start,
              "unique": role.unique, "names": dict(role.names)} for role in memory.relations.roles.values()]
    return {"version": 1, "companion": page.name, "you": you,
            "her": {"name": page.name, "language": page.language, "zone": memory.config.get("companion.zone"),
                    "card": page.card()},
            "me": {"name": page.me_name, "accounts": page.accounts, "fixed": page.fixed},
            "others": page.others, "roles": roles, "people": people_of(memory, gut, gut_view, you, page.names),
            "memory": page.limits(), "rows": page.rows(), "starts": list(STARTS if gut is not None else STARTS[:2]),
            "gut": gut_view}


def _name(value, what: str, longest: int = LONGEST) -> str:
    """A name: some words, at most `longest` characters."""
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > longest:
        raise ValueError(f"{what} is some words, at most {longest} characters")
    return value.strip()


def _table(value, what: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{what} is an object")
    return value


async def settle(page, asked) -> dict:
    """One save from the page (`settings`'s shape, any part of it), checked whole before any of it lands, so it lands
    whole or not at all; `start` is sent alone, as `$new` is typed alone. Returns the settings as they are then."""
    if not isinstance(asked, dict):
        raise ValueError("a save is an object: her, me, people, others, memory, rows, gut or start")
    unknown = [key for key in asked if key not in PARTS]
    if unknown:
        raise ValueError(f"not a part of the settings: {', '.join(unknown)}")
    gut, you = page.gut, page.you
    starts = STARTS if gut is not None else STARTS[:2]
    if asked.get("start") is not None:
        if len(asked) > 1:
            raise ValueError("start is sent alone")
        if asked["start"] not in starts:
            raise ValueError(f"start is {', '.join(starts)}")
        await page.start(asked["start"])
        return settings(page)
    memory = page.open()  # (her file, made if there is none yet: a save is something to keep)
    keep, config, work = {}, {}, []
    roles = memory.relations.roles

    def role_of(value, what: str) -> str:
        if value in ("", None):
            return ""
        if not isinstance(value, str) or value not in roles:
            raise ValueError(f"{what} is one of her roles, or ''")
        return value
    # Her
    her = _table(asked.get("her"), "her")
    if her.get("name") is not None:
        keep["display_name"] = _name(her["name"], "her name")
    if her.get("language") is not None:
        keep["reply_language"] = language_name(her["language"])
    if her.get("zone") is not None:
        config["companion.zone"] = check("companion.zone", her["zone"])
    if "card" in her:
        card = her["card"]
        if card is not None and not isinstance(card, dict):
            raise ValueError("a card is {text, on}, or null to take it away")
        if card and card.get("text") is not None and (not isinstance(card["text"], str) or not card["text"].strip()):
            raise ValueError("a card is some words")
        if card and card.get("on") is not None and not isinstance(card["on"], bool):
            raise ValueError("on is true or false")
        if card and card.get("on") is True and card.get("text") is None and page.card() is None:
            raise ValueError("there is no card yet")
        work.append(lambda: page.set_card(card))
    # People: you, your accounts, everyone she knows, and the role of people she meets
    me = _table(asked.get("me"), "me")
    if me.get("name") is not None:
        keep["call_owner"] = "" if me["name"] == "" else _name(me["name"], "your name", CALLED)
        work.append(page.called)
    linking, unlinking = _list(me.get("link")), _list(me.get("unlink"))
    for account in linking:
        if not isinstance(account, str) or not ACCOUNT.fullmatch(account.strip()):
            raise ValueError(f"not an account: {account} (a channel and an id, such as discord:42)")
        whose = page.whose(account.strip())
        if whose:
            raise ValueError(whose)
    for account in unlinking:
        if account in page.fixed:
            raise ValueError(f"{account} is joined to you in the students' settings (`people:`): it stays")
        if account not in page.accounts:
            raise ValueError(f"{account} is not one of your accounts")
    if linking or unlinking:
        work.append(lambda: page.relink([account.strip() for account in linking], unlinking))
    if "others" in asked:
        keep["met_role"] = role_of(asked["others"], "others")
    close, to_gut, moved = closeness_of(memory), [], []
    for person in _list(asked.get("people")):
        if not isinstance(person, dict) or not isinstance(person.get("subject"), str) or not person["subject"].strip():
            raise ValueError("a person is {subject, ...}")
        subject = person["subject"]
        role = role_of(person["role"], f"the role of {subject}") if person.get("role") is not None else None
        kind = (roles.get(close[subject]["role"]) if subject in close else None) if role is None else roles.get(role)
        if (person.get("closeness") is not None or person.get("hold") is not None) and kind is None:
            raise ValueError(f"{subject} has no role: closeness needs one")
        if person.get("closeness") is not None:
            _within(person["closeness"], kind.floor, kind.ceiling, f"closeness for {kind.key}")
        if person.get("hold") is not None and not isinstance(person["hold"], bool):
            raise ValueError("hold is true or false")
        if kind is not None and kind.unique and role is not None and role != (close.get(subject) or {}).get("role"):
            holder = next((other for other, found in close.items() if other != subject and found["role"] == kind.key),
                          None)
            if holder:
                raise ValueError(f"{holder} is her {kind.key} already: there is one")
        for_gut = {key: person[key] for key in GUT_ONLY if person.get(key) is not None}
        if for_gut:
            if gut is None:
                raise ValueError("she has no gut")
            to_gut.append({"subject": subject, **for_gut})
        if role is not None and page.given_role(subject) is not None:
            keep[f"role:{subject}"] = role  # (over `roles:`, which would give it back at the next start)
        moved.append(subject)

        def placed(subject=subject, person=person, role=role):
            relations = memory.relations
            if role == "":
                relations.remove(subject)
                return
            if role is not None and role != (close.get(subject) or {}).get("role"):
                relations.set(subject, role, closeness=person.get("closeness"))
            locked = subject in relations.locks()
            if person.get("hold") is False:
                relations.unlock(subject)
            holding = person["hold"] if person.get("hold") is not None else locked
            if holding:
                relations.lock(subject, person.get("closeness"))
            elif person.get("closeness") is not None:
                relations.set(subject, role or close[subject]["role"], closeness=person["closeness"])
        work.append(placed)
    # Memory
    values = _table(asked.get("memory"), "memory")
    for key, value in values.items():
        if key not in MEMORY:
            raise ValueError(f"not a memory setting the page sets: {key}")
        if key == "said_budget":
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= SAID:
                raise ValueError(f"said_budget is a whole number from 0 to {SAID}")
            keep["said"] = value
            continue
        config[f"memory.{key}"] = check(f"memory.{key}", value)
        if key.startswith("surface_"):
            keep[key] = config[f"memory.{key}"]  # (her settings give it at each start: so the page's is the latest)
    # The app's own rows
    rows = {row["key"]: row for row in page.rows()}
    for key, value in _table(asked.get("rows"), "rows").items():
        row = rows.get(key)
        if row is None or row["kind"] == "info":
            raise ValueError(f"not a setting here: {key}")
        if row["kind"] == "bool" and not isinstance(value, bool):
            raise ValueError(f"{key} is true or false")
        if row["kind"] == "number":
            _within(value, row.get("min", -math.inf), row.get("max", math.inf), key)
        keep[key] = value
    # Gut
    if asked.get("gut") is not None and gut is None:
        raise ValueError("she has no gut")
    changing = _table(asked.get("gut"), "gut")
    land = prepare(gut, {**changing, "people": [*_list(changing.get("people")), *to_gut]}) \
        if gut is not None and (changing or to_gut) else None
    # all of it checked: now it lands
    if config:
        memory.change(config)
    if gut is not None and "companion.zone" in config:
        gut.zone = memory.memory.zone
    for item in work:
        item()
    if land is not None:
        land()
    if keep:
        page.keep(keep)
    page.published(moved)
    return settings(page)

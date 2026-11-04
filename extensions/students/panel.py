"""A student's gut on her page: what the page shows (`view`, `starmap`) and the change it makes (`change`), as the
dsh-mneme-llm panel has them (plugin/panel.js), for the owner only.

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

import mneme_llm.gut as G


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
    # all of it checked: now it lands
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

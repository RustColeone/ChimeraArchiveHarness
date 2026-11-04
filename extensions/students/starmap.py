"""A student's heart as a star map, for her page: the same map dsh-mneme-llm's lib/starmap.js makes (and the mneme-llm
tuner draws), from her gut as it is now.

Her 26 ends sit evenly around a circle, the first at the top. Every row of her heart (one thing she can notice, such as
topic=rain or close=high, with a weight for each end) is a star: it sits where that row alone pulls her (a softmax of
its weights, each end's share drawn out along that end's arm), as bright as the row leans at all (its strongest weight
less its weakest), in the colour of the bar of its strongest end. The arms are how much more or less she feels each end
now than the day she was born, over her own latest lessons. Each person she knows is one star more, placed the same way
by what is different with them (their table's bias). In 3D (`DIRECTIONS`) her 14 bars are spread evenly over a sphere,
the first at the top, the two ends of a bar side by side, a little apart.

    found = starmap(gut)   # {ends, reach, probed, rows, directions, stars: [[x, y, bright, end, key, X, Y, Z]],
                           #  people: [{subject, x, y, at: [X, Y, Z], weight, lessons, end}]}
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mneme_llm.gut as G

SPREAD = 8.0  # how far a leaning row travels toward its end (her rows lean little: mostly under 1)
STARS = 1500  # stars sent: the rows that lean most
PROBE = 300  # her own latest lessons, which her arms are measured on
LEAST = 20  # with fewer lessons than this, every arm is as she was born
SHORTEST, LONGEST = .3, 2.4  # how far an arm can shrink or grow
GAIN = 3.0  # an arm grows by this much for each 1 of strength she has gained on an end (0 to 1)
APART = math.radians(12)  # in 3D, each end of a bar this far from the bar's own direction
# and how each bar's pair is turned about its direction, in degrees (`TURNS` in dsh-mneme-llm's lib/starmap.js)
TURNS = (114, 5, 88, 12, 143, 53, 144, 63, 64, 25, 114, 0, 0, 94)
ANGLES = tuple(-math.pi / 2 + 2 * math.pi * k / len(G.ENDS) for k in range(len(G.ENDS)))


def _directions() -> tuple:
    def unit(vector):
        length = math.sqrt(sum(value * value for value in vector))
        return [value / length for value in vector]

    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]

    golden, found = math.pi * (3 - math.sqrt(5)), []
    for index, (_, _, left, _) in enumerate(G.BARS):
        y = 1 - 2 * (index + .5) / len(G.BARS)
        r, turn = math.sqrt(1 - y * y), index * golden
        centre = [math.cos(turn) * r, y, math.sin(turn) * r]
        if not left:
            found.append(tuple(centre))
            continue
        across = unit(cross(centre, [1, 0, 0] if abs(y) > .99 else [0, 1, 0]))
        up = cross(centre, across)
        phi = math.radians(TURNS[index])
        side = [a * math.cos(phi) + u * math.sin(phi) for a, u in zip(across, up)]
        for sign in (-1, 1):
            found.append(tuple(unit([c * math.cos(APART) + sign * s * math.sin(APART) for c, s in zip(centre, side)])))
    return tuple(found)


DIRECTIONS = _directions()
ONE = (1.0,) * len(G.ENDS)


def shares(row) -> list[float]:
    """Each end's share of where a row sits: a softmax of its weights."""
    top = max(row)
    pulls = [math.exp(SPREAD * (weight - top)) for weight in row]
    total = sum(pulls)
    return [pull / total for pull in pulls]


def spot(row, reach=ONE) -> tuple[float, float]:
    x = y = 0.0
    for k, share in enumerate(shares(row)):
        x += share * reach[k] * math.cos(ANGLES[k])
        y += share * reach[k] * math.sin(ANGLES[k])
    return x, y


def spot3(row, reach=ONE) -> list[float]:
    at = [0.0, 0.0, 0.0]
    for k, share in enumerate(shares(row)):
        for axis in range(3):
            at[axis] += share * reach[k] * DIRECTIONS[k][axis]
    return at


def brightness(row) -> float:
    return max(row) - min(row)


def strongest(row) -> int:
    return list(row).index(max(row))


def strengths(table, probe) -> list[float]:
    """How strongly a table feels each end, on average over some moments ([form, closeness] each)."""
    sums = [0.0] * len(G.ENDS)
    for form, closeness in probe:
        for k, value in enumerate(table.strengths(G.features(form, closeness))):
            sums[k] += value
    return [value / max(1, len(probe)) for value in sums]


def arms(heart, born, probe) -> list[float]:
    """1 as she was born, longer by GAIN for each 1 of strength she has gained on an end since, shorter for what she has
    lost, from SHORTEST to LONGEST; with fewer than LEAST moments to measure on, each is 1."""
    if len(probe) < LEAST:
        return list(ONE)
    now, then = strengths(heart, probe), strengths(born, probe)
    return [min(LONGEST, max(SHORTEST, 1 + GAIN * (value - before))) for value, before in zip(now, then)]


_BIRTHS: dict[str, G.Table] = {}  # starter file → her heart as she was born, which never changes


def born(starter) -> G.Table:
    """Her heart as she was born: her starter, as `Gut.wake` starts a gut with no heart kept."""
    key = str(starter or "")
    if key not in _BIRTHS:
        net = G.Net()
        rows, _, known = G.read_starter(Path(key)) if key else ([], {}, G.ENDS)
        if rows:
            net.start(rows, known)
        _BIRTHS[key] = net.heart
    return _BIRTHS[key]


def probe_of(gut, count: int = PROBE) -> list:
    """The moments of her own latest lessons, [form, closeness] each, the newest first."""
    found = []
    for form, closeness in gut._open().execute("select form, closeness from lessons order by id desc limit ?", (count,)):
        try:
            form = json.loads(form)
        except ValueError:
            continue
        if isinstance(form, dict):
            found.append((form, closeness))
    return found


def starmap(gut, most: int = STARS) -> dict:
    """Her star map: up to `most` stars, the rows that lean most, and a star for each person she knows."""
    with gut.lock:
        net = gut.net
        heart = G.Table({"w": {key: list(row) for key, row in net.heart.w.items()}, "b": list(net.heart.b)})
        people = [(subject, list(found["table"].b), found["n"], net.weight(subject))
                  for subject, found in net.people.items()]
    probe = probe_of(gut)
    reach = arms(heart, born(gut.starter), probe)
    rows = sorted(((key, row, brightness(row)) for key, row in heart.w.items()), key=lambda item: (-item[2], item[0]))
    stars = [[round(value, 4) for value in spot(row, reach)] + [round(bright, 3), strongest(row), key]
             + [round(value, 4) for value in spot3(row, reach)] for key, row, bright in rows[:most]]
    found = [{"subject": subject, "x": round(spot(b, reach)[0], 4), "y": round(spot(b, reach)[1], 4),
              "at": [round(value, 4) for value in spot3(b, reach)], "weight": round(weight, 3), "lessons": round(n),
              "end": strongest(b)} for subject, b, n, weight in people]
    found.sort(key=lambda item: (-item["weight"], item["subject"]))
    return {"ends": list(G.ENDS), "reach": [round(value, 3) for value in reach], "probed": len(probe),
            "rows": len(heart.w), "directions": [[round(value, 5) for value in direction] for direction in DIRECTIONS],
            "stars": stars, "people": found}

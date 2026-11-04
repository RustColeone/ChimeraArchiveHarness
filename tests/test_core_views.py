"""Views: read-only data a module offers pages (contracts.View, InterfacePort.view)."""

import asyncio
import tempfile
import textwrap
import unittest
from pathlib import Path

from contracts import View, ViewError
from tests.core_support import iface, make_config, start_core

# A module with views: one for the owner, one for anyone, one for Ivy alone, one that fails, a slow one, a big one.
MODULE = '''
import asyncio

from contracts import Contributions, Extension, Persona, View

ASKED = []


async def board(persona, person):
    ASKED.append((persona, person))
    return {"persona": persona, "person": list(person), "stars": list(range(3))}


async def boom(persona, person):
    raise RuntimeError("boom")


async def slow(persona, person):
    await asyncio.sleep(5)


async def big(persona, person):
    return "x" * 1_100_000


def setup(context):
    return Contributions(
        personas=[Persona("ivy", "Ivy", "You are Ivy.")],
        views=[View("board", board), View("open", board, access="member"), View("hers", board, personas=("ivy",)),
               View("boom", boom), View("slow", slow, timeout_s=0.2), View("big", big)])


EXTENSION = Extension("viewmod", setup)
'''


class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        folder = self.tmp / "viewmod"
        folder.mkdir()
        (folder / "extension.py").write_text(textwrap.dedent(MODULE), encoding="utf-8")
        extensions = [*make_config(self.tmp).raw["modules"]["paths"], str(folder)]
        self.core = await start_core(self.tmp, {"extensions": extensions})
        self.asked = next(item.module for item in self.core.extensions if item.extension.name == "viewmod").ASKED

    async def asyncTearDown(self):
        await self.core.stop()
        self._tmp.cleanup()

    async def refused(self, code, *arguments, interface="chat"):
        with self.assertRaises(ViewError) as caught:
            await iface(self.core, interface).port.view(*arguments)
        self.assertEqual(caught.exception.code, code)

    async def test_a_page_reads_a_view_for_whoever_asks_and_nothing_is_kept(self):
        port = iface(self.core).port
        self.assertEqual(await port.view("viewmod.board", "ivy", "boss"),
                         {"persona": "ivy", "person": ["chat", "boss"], "stars": [0, 1, 2]})
        self.assertEqual(await port.view("viewmod.board", "p", "boss"), {"persona": "p", "person": ["chat", "boss"],
                                                                        "stars": [0, 1, 2]})
        self.assertEqual(self.asked, [("ivy", ("chat", "boss")), ("p", ("chat", "boss"))])  # worked out each time
        self.assertEqual((await port.view("viewmod.open", "ivy", "alice"))["person"], ["chat", "alice"])
        self.assertEqual(self.core.manager.tank.runs(address="chat:view"), [])  # (no run, nothing recorded)

    async def test_access_personas_and_names_are_checked(self):
        await self.refused("forbidden", "viewmod.board", "ivy", "alice")  # the owner's: alice is a member
        await self.refused("unknown", "viewmod.nothing", "ivy", "boss")
        await self.refused("unknown", "viewmod.board", "nobody", "boss")
        await self.refused("unknown", "viewmod.hers", "p", "boss")
        self.assertEqual((await iface(self.core).port.view("viewmod.hers", "ivy", "boss"))["persona"], "ivy")
        await self.refused("unknown", "board", "ivy", "boss")  # (a view is named by its module)

    async def test_a_view_that_fails_takes_too_long_or_is_too_big_says_so(self):
        await self.refused("failed", "viewmod.boom", "ivy", "boss")
        await self.refused("failed", "viewmod.slow", "ivy", "boss")
        await self.refused("too_big", "viewmod.big", "ivy", "boss")
        self.assertEqual((await iface(self.core).port.view("viewmod.open", "ivy", "boss"))["persona"], "ivy")

    def test_a_view_is_checked_when_it_is_made(self):
        async def read(persona, person):
            return None
        for bad in ({"name": "Bad Name"}, {"access": "owner"}, {"personas": [""]}, {"timeout_s": 0}):
            with self.assertRaises(ValueError):
                View(**{"name": "ok", "read": read, **bad})
        self.assertEqual(View("ok", read, personas="ivy").personas, ("ivy",))


if __name__ == "__main__":
    unittest.main()

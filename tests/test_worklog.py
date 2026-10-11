import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import DEMO, TempHome

from hearthwood import cli, worklog

HOSTILE = '</script><script>window.PWNED=1</script><img src=x onerror="alert(1)"> <b>bold</b>'


def manager(*argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(list(argv))


def embedded(page):
    """{board: cards} from the page's JSON elements."""
    out = {}
    for board, raw in re.findall(r'<script type=application/json class=cards data-board="([^"]*)">(.*?)</script>', page, re.S):
        out[board] = json.loads(raw)
    return out


class Page(unittest.TestCase):
    def build(self, edit=None):
        """The demo board, copied (and edited) into a temporary folder, read and analysed: the page's text."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        board = Path(self.tmp.name) / "board"
        shutil.copytree(DEMO, board)
        if edit:
            edit(board)
        t = TempHome().__enter__()
        self.addCleanup(t.__exit__)
        self.t = t
        self.assertEqual(manager("connect", "markdown", str(board), "--board", "demo"), 0)
        self.assertEqual(manager("analyze", "--read", "--facts-only"), 0)
        return (t.h / "log.html").read_text()

    def test_card_numbers_open_the_panel(self):
        page = self.build()
        self.assertIn('<button type=button class=key data-key="LAN-5">LAN-5</button>', page)
        self.assertIn('<aside id=panel role=dialog', page)
        self.assertIn('<section class=board data-board="demo">', page)

    def test_only_the_cards_the_page_mentions_are_whole(self):
        page = self.build()
        cards = embedded(page)["demo"]
        shown = set(re.findall(r'class=key data-key="([^"]+)"', page))
        whole = {k for k, c in cards.items() if not c.get("stub")}
        self.assertEqual(whole, shown)
        for k, c in cards.items():
            if c.get("stub"):
                self.assertNotIn("body", c)

    def test_every_card_on_the_board_can_open(self):
        page = self.build()
        cards = embedded(page)["demo"]
        self.assertEqual(set(cards), {p.stem for p in DEMO.glob("LAN-*.md")})
        self.assertTrue(cards["LAN-2"]["stub"])
        self.assertEqual(cards["LAN-2"]["title"], "Store notes in a local database")

    def test_the_finding_arrow_is_drawn_on_the_summary_line(self):
        self.assertIn("details>summary::-webkit-details-marker{display:none}", worklog.CSS)
        self.assertIn("content:'\u25b8'", worklog.CSS)

    def test_a_card_keeps_its_closest_matches(self):
        page = self.build()
        cards = embedded(page)["demo"]
        self.assertEqual(cards["LAN-8"]["similar"][0][0], "LAN-7")

    def test_a_card_cannot_break_out_of_the_page(self):
        def edit(board):
            p = board / "LAN-7.md"
            s = p.read_text().replace("title: Search inside notes", "title: Search inside notes " + HOSTILE)
            p.write_text(s.replace("fast enough to type into.", "fast enough to type into. " + HOSTILE))
        page = self.build(edit)
        self.assertNotIn("<script>window.PWNED", page)
        self.assertNotIn("<img src=x", page)
        card = embedded(page)["demo"]["LAN-7"]
        self.assertIn(HOSTILE, card["body"])
        self.assertIn(HOSTILE, card["title"])

    def test_people_stay_out_unless_turned_on(self):
        def edit(board):
            p = board / "LAN-7.md"
            p.write_text(p.read_text().replace("labels: [search]", "labels: [search]\nassignees: [sam]"))
        page = self.build(edit)
        self.assertNotIn("assignees", json.dumps(embedded(page)["demo"]))
        toml = self.t.h / "boards" / "demo" / "board.toml"
        toml.write_text(toml.read_text().replace("people = false", "people = true"))
        worklog.build(self.t.h)
        self.assertEqual(embedded((self.t.h / "log.html").read_text())["demo"]["LAN-7"]["assignees"], ["sam"])

    def test_the_panel_builds_nodes_from_text_only(self):
        self.assertNotIn("innerHTML", worklog.JS)
        self.assertNotIn("insertAdjacentHTML", worklog.JS)
        self.assertNotIn("</script", worklog.JS)


class Embed(unittest.TestCase):
    def test_no_less_than_sign_survives(self):
        raw = worklog.embed({"a": "</script><b>"})
        self.assertNotIn("<", raw)
        self.assertEqual(json.loads(raw), {"a": "</script><b>"})


if __name__ == "__main__":
    unittest.main()

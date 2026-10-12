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

    def test_comments_reach_the_panel_without_people(self):
        page = self.build()
        talk = embedded(page)["demo"]["LAN-7"]["thread"]
        self.assertEqual(len(talk), 2)
        self.assertNotIn("author", talk[0])
        self.assertIn("@someone and I agreed", talk[1]["body"])
        self.assertFalse(any(m["new"] for m in talk))
        toml = self.t.h / "boards" / "demo" / "board.toml"
        toml.write_text(toml.read_text().replace("people = false", "people = true"))
        worklog.build(self.t.h)
        talk = embedded((self.t.h / "log.html").read_text())["demo"]["LAN-7"]["thread"]
        self.assertEqual(talk[1]["author"], "sam")
        self.assertIn("@ana", talk[1]["body"])

    def test_the_active_tab_has_a_filter(self):
        page = self.build()
        self.assertIn("<input class=filter id=activefilter", page)
        self.assertIn("class='card readylist'", page)
        self.assertIn("getElementById('activefilter')", page)

    def test_the_static_page_says_where_a_stub_is_read_whole(self):
        page = self.build()
        self.assertIn("Open it with manager ui to read every card whole.", page)
        self.assertIn("if(window.hwCard&&!c.unread)", page)

    def test_the_claude_tab_on_the_static_page_shows_commands(self):
        page = self.build()
        self.assertIn("data-tab=claude", page)
        self.assertIn("manager model reading opus|sonnet", page)
        self.assertIn("manager analyze --read -b demo", page)
        self.assertNotIn("href=#calls", page)                       # no top-row button that goes nowhere
        self.assertNotIn("class=runbox", page)

    def test_links_to_the_tracker_open_in_a_new_tab(self):
        page = self.build()
        self.assertEqual(page.count("a.target='_blank'"), 2)

    def test_the_page_says_what_to_do_next(self):
        page = self.build()
        self.assertIn("<span class=nlabel>next</span><code>manager review -b demo</code>", page)

    def test_badges_say_severity(self):
        page = self.build()
        self.assertIn("<span class='badge high'>high</span>", page)
        self.assertIn("<span class='badge medium'>medium</span>", page)
        self.assertNotIn("chip sev-", page)

    def test_three_tabs_and_their_views(self):
        page = self.build()
        for tab in ("active", "all", "stats"):
            self.assertIn(f"role=tab data-tab={tab}", page)
        self.assertIn("<div class=view data-view=active>", page)
        self.assertIn("<div class=view data-view=all hidden>", page)
        self.assertIn("<div class=view data-view=stats hidden>", page)
        self.assertIn('class=allist data-columns="[&quot;Backlog&quot;', page)

    def test_the_stats_chart_closes_every_element(self):
        page = self.build()
        svg = page[page.index('<svg class="chart"'):page.index("</svg>")]
        self.assertNotIn("/>", svg)
        self.assertEqual(svg.count("<line"), svg.count("</line>"))
        self.assertIn('data-tip="', svg)
        self.assertIn("Table view", page)

    def test_the_static_page_shows_the_command_instead_of_buttons(self):
        page = self.build()
        self.assertIn('<div class=cmdhint>manager verdict', page)
        self.assertNotIn("<div class=acts", page)
        self.assertNotIn("Discuss this with Spirit", page)

    def test_the_panel_builds_nodes_from_text_only(self):
        self.assertNotIn("innerHTML", worklog.JS)
        self.assertNotIn("insertAdjacentHTML", worklog.JS)
        self.assertNotIn("</script", worklog.JS)


class Prose(unittest.TestCase):
    """Card numbers inside the reading's sentences and the findings' sentences open the card."""

    def read(self, summary, why):
        with TempHome() as t:
            self.assertEqual(manager("connect", "markdown", str(DEMO), "--board", "demo"), 0)
            self.assertEqual(manager("analyze", "--read"), 0)
            d = sorted((t.h / "boards" / "demo" / "analyses").iterdir())[-1]
            r = json.loads((d / "reading.json").read_text())
            r["summary"], r["attention"][0]["why"] = summary, why
            (d / "reading.json").write_text(json.dumps(r))
            worklog.build(t.h)
            return (t.h / "log.html").read_text()

    def test_a_card_named_in_the_reading_opens(self):
        page = self.read("LAN-19 was closed as not planned.", "LAN-2 and LAN-20 are both done.")
        self.assertIn('<button type=button class=key data-key="LAN-19">LAN-19</button> was closed', page)
        self.assertIn('<button type=button class=key data-key="LAN-20">LAN-20</button> are both', page)
        self.assertFalse(embedded(page)["demo"]["LAN-19"].get("stub"))

    def test_only_real_cards_as_whole_words(self):
        page = self.read("Not LAN-99, xLAN-2, LAN-2x or #LAN-2.", "nothing")
        self.assertIn("Not LAN-99, xLAN-2, LAN-2x or #LAN-2.", page)

    def test_a_reading_cannot_inject_markup(self):
        page = self.read("LAN-19 " + HOSTILE, "LAN-2</script><b>x</b>")
        self.assertNotIn("<script>window.PWNED", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn('data-key="LAN-2">LAN-2</button>&lt;/script&gt;&lt;b&gt;x', page)

    def test_the_findings_sentences_link_too(self):
        with TempHome() as t:
            manager("connect", "markdown", str(DEMO), "--board", "demo")
            manager("analyze", "--read", "--facts-only")
            page = (t.h / "log.html").read_text()
        self.assertRegex(page, r'<p>[^<]*<button type=button class=key data-key="LAN-18">LAN-18</button> &quot;Rich text')


class Embed(unittest.TestCase):
    def test_no_less_than_sign_survives(self):
        raw = worklog.embed({"a": "</script><b>"})
        self.assertNotIn("<", raw)
        self.assertEqual(json.loads(raw), {"a": "</script><b>"})


if __name__ == "__main__":
    unittest.main()

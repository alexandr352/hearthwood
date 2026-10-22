"""Cards outside the snapshot that a card on it points to: read by key, shown where they stand, never counted."""

import contextlib
import io
import json
import unittest

from helpers import TempHome, board, item, settings

from hearthwood import cli, facts, home, worklog
from hearthwood.adapters import jira
from hearthwood.model import outside_keys

from test_github import FakeGitHub, issue as gh_issue
from hearthwood.adapters import github
from test_jira import CLOUD, SITE, FakeAtlassian, blocked_by, issue as jira_issue


def run(b, **rules):
    return facts.Analysis(b, settings(**rules)).run()


def finding(a, rule):
    return next(f for f in a.findings if f.rule == rule)


class Facts(unittest.TestCase):
    def test_a_blocker_finished_long_ago_does_not_block(self):
        a = run(board(item("#2", blocked_by=["#1"]),
                      outside=[item("#1", state="closed", column="Done", close_reason="completed")]))
        self.assertEqual(a.ready, ["#2"])
        self.assertNotIn("blocked", {f.rule for f in a.findings})

    def test_an_open_blocker_outside_says_where_it_stands(self):
        a = run(board(item("#2", blocked_by=["OLD-1"]),
                      outside=[item("OLD-1", column="In Progress", fields={"sprint": "Sprint 9"})]))
        f = finding(a, "blocked")
        self.assertIn("OLD-1 (In Progress, Sprint 9, outside the snapshot) is not finished", f.says)
        self.assertEqual(f.evidence["where"]["OLD-1"],
                         {"column": "In Progress", "sprint": "Sprint 9", "state": "open", "outside": True})

    def test_a_blocker_on_the_board_says_where_it_stands_too(self):
        a = run(board(item("#1", column="In Progress"), item("#2", blocked_by=["#1"])))
        self.assertIn("#1 (In Progress) is not finished", finding(a, "blocked").says)

    def test_a_blocker_that_could_not_be_read_stays_unknown(self):
        a = run(board(item("#2", blocked_by=["#77"])))
        f = finding(a, "blocked")
        self.assertIn("not in the snapshot", f.says)
        self.assertEqual(f.evidence["where"]["#77"], {"unknown": True})

    def test_outside_cards_are_never_the_boards_work(self):
        a = run(board(item("#2", blocked_by=["#1"]), outside=[item("#1"), item("#3")]))
        self.assertEqual(a.flow["open"], 1)
        self.assertNotIn("#1", a.ready)
        self.assertNotIn("#3", a.ready)

    def test_the_reading_sees_them_apart(self):
        b = board(item("#2", blocked_by=["#1"]), outside=[item("#1", column="In Progress"), item("#9")])
        text = facts.board_index(b, run(b))
        head, _, tail = text.partition("# Outside the snapshot")
        self.assertIn("#2 |", head)
        self.assertIn("#1 |", tail)
        self.assertNotIn("#9 |", text)              # outside, and nothing on the board points to it

    def test_which_keys_are_read(self):
        items = [item("#2", blocked_by=["#1", "#8"], blocking=["#5"], parent="#7"),
                 item("#3", state="closed", blocked_by=["#40"]), item("#8")]
        self.assertEqual(outside_keys(items), (["#1", "#5", "#7"], 0))       # blockers first; a closed card's are not
        self.assertEqual(outside_keys(items, limit=1), (["#1"], 2))


class Jira(unittest.TestCase):
    def test_keys_outside_the_window_are_read_and_the_missing_named(self):
        old = jira_issue("OLD-1", status=("99", "Closed", "done"), resolution="Done", resolved="2025-01-01T00:00:00.000+0000",
                         assignee="Ann Blocker")
        fake = FakeAtlassian([[jira_issue("APP-2", links=[blocked_by("OLD-1"), blocked_by("APP-9")])]])
        fake.outside = {"OLD-1": old}
        b = jira.read_board("t", CLOUD, SITE, "APP", lambda: "Bearer T", transport=fake, sleep=lambda s: None)
        self.assertEqual([i.key for i in b.items], ["APP-2"])
        (o,) = b.outside
        self.assertEqual((o.key, o.state, o.column, o.column_source), ("OLD-1", "closed", "Closed", "status"))
        self.assertTrue(any("1 cards outside this snapshot were read" in n for n in b.notes))
        self.assertTrue(any("could not be read" in n and "APP-9" in n for n in b.notes))
        self.assertTrue(all(c[0] == "GET" or c[1].endswith("/search/jql") for c in fake.calls))   # reads only
        a = facts.Analysis(b, settings()).run()
        self.assertEqual(finding(a, "blocked").evidence["blockers"], {"APP-9": "unknown"})   # OLD-1 is finished

    def test_a_page_of_keys_is_read_in_one_search(self):
        fake = FakeAtlassian([[jira_issue("APP-2", links=[blocked_by("OLD-1"), blocked_by("OLD-2")])]])
        fake.outside = {"OLD-1": jira_issue("OLD-1"), "OLD-2": jira_issue("OLD-2")}
        b = jira.read_board("t", CLOUD, SITE, "APP", lambda: "Bearer T", transport=fake, sleep=lambda s: None)
        self.assertEqual(sorted(i.key for i in b.outside), ["OLD-1", "OLD-2"])
        self.assertEqual(sum(1 for c in fake.calls if c[1].startswith("/rest/api/3/issue/")), 0)

    def test_only_five_comments_by_default(self):
        many = [{"created": f"2026-09-{d:02d}T10:00:00.000+0000", "author": {"displayName": "x"}, "body": f"c{d}"}
                for d in range(1, 10)]
        fake = FakeAtlassian([[jira_issue("APP-2", links=[blocked_by("OLD-1")])]])
        fake.outside = {"OLD-1": jira_issue("OLD-1", comments=many)}
        b = jira.read_board("t", CLOUD, SITE, "APP", lambda: "Bearer T", transport=fake, sleep=lambda s: None)
        self.assertEqual([c.body for c in b.outside[0].thread], ["c5", "c6", "c7", "c8", "c9"])


class GitHub(unittest.TestCase):
    def test_issues_outside_the_window_are_read_by_number(self):
        fake = FakeGitHub([[gh_issue(2, blocked_by=[1], statuses=[("", "Todo")])]], [[]])
        two = fake.open[0][0]
        two["blockedBy"]["nodes"].append({"number": 5, "repository": {"nameWithOwner": "o/other"}})
        two["blockedBy"]["nodes"].append({"number": 6, "repository": {"nameWithOwner": "o/other"}})
        fake.outside[("o", "r", 1)] = gh_issue(1, state="CLOSED", reason="COMPLETED", closed="2025-01-01T00:00:00Z",
                                               updated="2025-01-01T00:00:00Z")
        fake.outside[("o", "other", 5)] = gh_issue(5)
        b = github.read_board("t", "o/r", token="T", transport=fake, closed_days=60)
        self.assertEqual(sorted(i.key for i in b.outside), ["#1", "o/other#5"])
        self.assertTrue(any("could not be read" in n and "o/other#6" in n for n in b.notes))
        a = facts.Analysis(b, settings()).run()
        self.assertEqual(finding(a, "blocked").evidence["blockers"], {"o/other#5": "open", "o/other#6": "unknown"})


def manager(*argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(list(argv))


class Page(unittest.TestCase):
    def page(self, people=False):
        t = TempHome().__enter__()
        self.addCleanup(t.__exit__)
        b = home.add_board("work", "github", "o/r", h=t.h)
        if people:
            p = b.dir / "board.toml"
            p.write_text(p.read_text().replace("people = false", f"people = {people}"))
        snap = board(item("#2", blocked_by=["#1"], assignees=["kim"]),
                     outside=[item("#1", column="In Progress", assignees=["zoltana"], fields={"sprint": "Sprint 9"})])
        b.snapshots.mkdir(parents=True, exist_ok=True)
        (b.snapshots / "20261010-000000.json").write_text(snap.to_json())
        self.assertEqual(manager("analyze", "--facts-only", "-b", "work"), 0)
        return (t.h / "log.html").read_text()

    def cards(self, page):
        import re
        raw = re.search(r'<script type=application/json class=cards data-board="work">(.*?)</script>', page, re.S).group(1)
        return json.loads(raw)

    def test_an_outside_blocker_opens_in_the_panel_and_is_marked(self):
        page = self.page()
        c = self.cards(page)
        self.assertTrue(c["#1"]["outside"])
        self.assertFalse(c["#2"]["outside"])
        self.assertIn('data-key="#1">#1</button>', page)
        self.assertNotIn("assignees", c["#1"])           # people = false: no names anywhere
        self.assertNotIn("Who to ask", page)
        self.assertNotIn("zoltana", page)

    def test_names_show_who_to_ask_on_the_page_only(self):
        page = self.page(people='"names"')
        self.assertIn("<b>Who to ask:</b>", page)
        self.assertIn("zoltana", page)
        self.assertEqual(self.cards(page)["#1"]["assignees"], ["zoltana"])

    def test_the_tracker_link_is_known_for_cards_not_read(self):
        self.assertEqual(worklog.tracker_link(type("B", (), {"source": "github", "where": "o/r", "settings": {}})()),
                         {"kind": "github", "base": "https://github.com/o/r"})
        self.assertEqual(worklog.tracker_link(type("B", (), {"source": "jira", "where": "x", "settings": {"site": SITE + "/"}})()),
                         {"kind": "jira", "base": SITE})
        self.assertEqual(worklog.tracker_link(type("B", (), {"source": "jira", "where": "x",
                                                             "settings": {"site": "javascript:alert(1)"}})()), {})
        self.assertEqual(worklog.tracker_link(type("B", (), {"source": "markdown", "where": "/x", "settings": {}})()), {})


class Views(Page):
    def test_two_views_holding_the_same_cards_say_so(self):
        page = self.page()
        self.assertIn("<p class='mute small same' data-variant=all-recent>Last 60 days and All time hold the same card "
                      "here: the one card on this board was updated in the last 60 days.</p>", page)
        self.assertIn("data-variant=all-all>Last 60 days and All time hold the same card", page)

    def test_a_second_board_brings_the_board_switch_and_the_real_board_comes_first(self):
        page = self.page()
        self.assertNotIn("class='scope boardswitch'", page)
        self.assertEqual(manager("connect", "demo"), 0)
        page = worklog.render(home.home_dir())
        self.assertIn("<span class='scope boardswitch' role=group aria-label='Which board' data-first=\"work\">", page)
        self.assertIn('data-b="demo" aria-pressed=false>demo<span class=tag>demo</span></button>', page)
        self.assertIn('data-b="work" aria-pressed=true>work</button>', page)


if __name__ == "__main__":
    unittest.main()

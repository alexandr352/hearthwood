import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import TempHome, board, item, settings

from hearthwood import facts, home, sprints, stats, worklog
from hearthwood.adapters import jira


def sp(name, state, start="", end="", goal=""):
    return {"sprint": name, "sprint_state": state, "sprint_start": start, "sprint_end": end, "sprint_goal": goal}


def sprint_board():
    return board(
        item("#1", column="In Progress", fields=sp("Sprint 9", "active", "2026-10-06T00:00:00Z", "2026-10-20T00:00:00Z", "ship sync")),
        item("#2", column="Todo", fields=sp("Sprint 9", "active", "2026-10-06T00:00:00Z", "2026-10-20T00:00:00Z")),
        item("#3", state="closed", column="Done", close_reason="completed", closed="2026-10-08T00:00:00Z",
             fields=sp("Sprint 9", "active", "2026-10-06T00:00:00Z", "2026-10-20T00:00:00Z")),
        item("#4", column="Todo", fields=sp("Groomed", "future")),
        item("#5", column="Todo", fields=sp("Sprint 10", "future", "2026-10-20T00:00:00Z")),
        item("#6", column="Todo", updated="2026-09-01T00:00:00Z", fields=sp("Sprint 8", "closed", "2026-09-22T00:00:00Z", "2026-10-06T00:00:00Z")),
        item("#7", column="Todo"))


class Order(unittest.TestCase):
    def test_active_then_future_by_start_then_closed(self):
        self.assertEqual([s["name"] for s in sprints.ordered(sprint_board().items)], ["Sprint 9", "Sprint 10", "Groomed", "Sprint 8"])

    def test_newer_coming_sprints_first_and_parking_after(self):
        b = board(item("#1", updated="2023-01-01T00:00:00Z", fields=sp("Old plan", "future", "2022-09-01T00:00:00Z")),
                  item("#2", updated="2026-10-09T00:00:00Z", fields=sp("Next", "future", "2026-10-20T00:00:00Z")),
                  item("#3", updated="2026-10-08T00:00:00Z", fields=sp("Ideas", "future")),
                  item("#6", updated="2024-05-01T00:00:00Z", fields=sp("Leftovers", "future")),
                  item("#4", fields=sp("S1", "closed", "2026-01-01T00:00:00Z", "2026-01-14T00:00:00Z")),
                  item("#5", fields=sp("S2", "closed", "2026-02-01T00:00:00Z", "2026-02-14T00:00:00Z")))
        # coming first; then parking, most recently worked-on first ("Old plan" started in 2022: parking now)
        self.assertEqual([s["name"] for s in sprints.ordered(b.items)], ["Next", "Ideas", "Leftovers", "Old plan", "S2", "S1"])

    def test_the_running_sprints_cards_include_the_finished_ones(self):
        self.assertEqual(sprints.active_keys(sprint_board().items), {"#1", "#2", "#3"})

    def test_no_sprints_no_sprint(self):
        b = board(item("#1"), item("#2"))
        self.assertEqual((sprints.ordered(b.items), sprints.active_keys(b.items)), ([], set()))

    def test_the_current_sprint_of_a_carried_over_card(self):
        self.assertEqual(jira.current_sprint([{"name": "S7", "state": "closed"}, {"name": "S8", "state": "active"},
                                              {"name": "S9", "state": "future"}])["name"], "S8")
        self.assertEqual(jira.current_sprint([{"name": "S7", "state": "closed"}, {"name": "S9", "state": "future"}])["name"], "S9")
        self.assertIsNone(jira.current_sprint(None))


class Facts(unittest.TestCase):
    def test_this_sprint_section_and_findings(self):
        a = facts.Analysis(sprint_board(), settings(stale_days=7)).run()
        s = a.sprint()
        self.assertEqual([x["name"] for x in s["active"]], ["Sprint 9"])
        self.assertEqual(s["keys"], ["#1", "#2", "#3"])
        self.assertEqual(s["active"][0]["cards"], 3)
        md = a.to_markdown()
        self.assertIn("## This sprint", md)
        self.assertIn("Sprint 9: 2026-10-06 to 2026-10-20, 3 cards", md)
        self.assertIn("goal: ship sync", md)
        self.assertIn("- cards in the sprint: #1, #2, #3", md)
        self.assertLess(md.index("## This sprint"), md.index("## Findings"))
        self.assertTrue(all(set(f.keys) & {"#1", "#2", "#3"} for f in a.findings if f.id in s["findings"]))

    def test_no_section_without_a_running_sprint(self):
        self.assertNotIn("## This sprint", facts.Analysis(board(item("#1")), settings()).run().to_markdown())


class Recent(unittest.TestCase):
    def test_long_untouched_cards_are_one_finding(self):
        b = board(item("#1", column="In Progress", updated="2026-10-01T00:00:00Z"),          # 9 days: stale
                  item("#2", column="In Progress", updated="2025-01-01T00:00:00Z"),          # over 180 days
                  item("#3", column="In Review", updated="2023-03-01T00:00:00Z"))
        a = facts.Analysis(b, settings()).run()
        stale = [f for f in a.findings if f.rule == "stale"]
        dead = [f for f in a.findings if f.rule == "long-untouched"]
        self.assertEqual([f.keys for f in stale], [["#1"]])
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0].keys, ["#3", "#2"])                                       # oldest first
        self.assertIn("2 cards", dead[0].title)

    def test_findings_about_recent_cards_come_first_and_old_ones_are_marked(self):
        b = board(item("#1", column="In Progress", updated="2026-09-01T00:00:00Z"),
                  item("#2", column="In Progress", updated="2026-06-01T00:00:00Z"))
        page = Page().page(b)
        i, j = page.index(">#1</button> has not moved"), page.index(">#2</button> has not moved")
        self.assertLess(i, j)
        self.assertRegex(page, r"\d+ about cards touched in the last 60 days, 1 older")
        self.assertEqual(page.count("<details class='card finding older'>"), 1)


class Stats(unittest.TestCase):
    def test_the_sprints_table(self):
        rows = stats.Stats(sprint_board(), settings()).sprints()
        self.assertEqual([r["name"] for r in rows], ["Sprint 9", "Sprint 10", "Groomed"])     # closed ones left out
        nine = rows[0]
        self.assertEqual((nine["cards"], nine["open"], nine["done"], nine["active"], nine["waiting"], nine["progress"]),
                         (3, 2, 1, 1, 1, 33))


class Page(unittest.TestCase):
    def page(self, b):
        with TempHome() as t:
            bh = home.add_board("work", "markdown", "x", h=t.h)
            bh.snapshots.mkdir(parents=True, exist_ok=True)
            (bh.snapshots / "20261012-000000.json").write_text(b.to_json())
            a = facts.Analysis(b, bh.settings).run()
            from hearthwood import reading
            reading.prepare(bh, b, a, {})
            return worklog.render(t.h)

    def test_a_sprint_board_gets_the_scope_switch_and_the_grouping(self):
        page = self.page(sprint_board())
        self.assertIn("data-scope=sprint aria-pressed=true>This sprint", page)
        self.assertIn("Sprint 9", page)
        keys = json.loads(re.search(r'<script type=application/json class=insprint data-board="work">(.*?)</script>', page).group(1))
        self.assertEqual(keys, ["#1", "#2", "#3"])
        self.assertIn("data-group=sprint aria-pressed=true>by sprint", page)
        order = json.loads(re.search(r'data-sprints="([^"]*)"', page).group(1).replace("&quot;", '"'))
        self.assertEqual([s["name"] for s in order], ["Sprint 9", "Sprint 10", "Groomed", "Sprint 8"])
        self.assertIn("Sprints: running and coming", page)
        for v in ("sprint-recent", "sprint-all", "all-recent", "all-all"):         # a ready list per view
            self.assertIn(f"<div class='card readylist' data-variant={v}>", page)
        self.assertIn("data-time=recent aria-pressed=true>Last 60 days", page)

    def test_a_board_without_sprints_keeps_the_old_page(self):
        page = self.page(board(item("#1"), item("#2")))
        self.assertNotIn("data-scope=sprint aria-pressed", page)
        self.assertNotIn("data-group=sprint", page)
        self.assertNotIn("Sprints: running and coming", page)
        self.assertIn("data-time=recent aria-pressed=true>Last 60 days", page)     # the time switch is for every board


if __name__ == "__main__":
    unittest.main()

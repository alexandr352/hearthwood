"""Siblings the board declares, ready work on a board whose backlog lives in To Do, and the people setting."""

import unittest

from helpers import board, item, settings

from hearthwood import facts, home


def run(b, **rules):
    return facts.Analysis(b, settings(**rules)).run()


def rules_of(a):
    return [f.rule for f in a.findings]


PATTERNS = [r"(?i)\b(android|ios|unity)\b", "^Design - "]
LONG = "The same long description of a settings screen, shared word for word by both cards here."


class Siblings(unittest.TestCase):
    def test_platform_twins_are_siblings_not_duplicates(self):
        b = board(item("#1", title="SDK - Android: offline mode", body=LONG),
                  item("#2", title="SDK - iOS: offline mode", body=LONG))
        self.assertIn("duplicate", rules_of(run(b)))
        a = run(b, sibling_patterns=PATTERNS)
        self.assertNotIn("duplicate", rules_of(a))
        self.assertEqual(a.siblings, {"#1": ["#2"], "#2": ["#1"]})
        self.assertIn("groups of siblings", a.to_markdown())

    def test_a_design_card_and_its_build_card_are_siblings(self):
        a = run(board(item("#1", title="Design - Export to PDF", body=LONG), item("#2", title="Export to PDF", body=LONG)),
                sibling_patterns=PATTERNS)
        self.assertNotIn("duplicate", rules_of(a))

    def test_the_same_title_twice_is_still_a_duplicate(self):
        a = run(board(item("#1", title="SDK - Android: offline mode", body=LONG),
                      item("#2", title="SDK - Android: offline mode", body=LONG)), sibling_patterns=PATTERNS)
        self.assertIn("duplicate", rules_of(a))
        self.assertEqual(a.siblings, {})

    def test_a_finished_sibling_is_not_done_before(self):
        a = run(board(item("#1", title="Design - Export to PDF", body=LONG, state="closed", column="Done",
                           close_reason="completed", closed="2026-10-01T00:00:00Z"),
                      item("#2", title="Export to PDF", body=LONG)), sibling_patterns=PATTERNS)
        self.assertNotIn("done-before", rules_of(a))

    def test_a_broken_pattern_is_named(self):
        with self.assertRaisesRegex(ValueError, "sibling_patterns"):
            run(board(item("#1")), sibling_patterns=["(unclosed"])


def sprint(name="Sprint 9", state="active"):
    return {"sprint": name, "sprint_state": state, "sprint_start": "2026-10-01T00:00:00Z"}


class ReadyInSprint(unittest.TestCase):
    def backlog(self):
        """25 open cards, 22 of them waiting in To Do; two of the waiting ones are in the running sprint."""
        cards = [item(f"#{n}", column="To Do") for n in range(1, 21)]
        cards += [item("#21", column="To Do", fields=sprint()), item("#22", column="To Do", fields=sprint()),
                  item("#23", column="In Progress", fields=sprint()), item("#24", column="In Progress"),
                  item("#25", column="In Review")]
        return board(*cards)

    def test_auto_counts_only_the_sprint_when_the_backlog_waits_in_to_do(self):
        a = run(self.backlog())
        self.assertEqual(a.ready, ["#21", "#22"])
        self.assertEqual(len(a.ready_all), 22)
        f = next(x for x in a.findings if x.rule == "ready")
        self.assertEqual(f.title, "2 items are ready to start in the running sprint")
        self.assertIn("20 more cards in To Do are unblocked but outside the running sprint. To Do holds 22 of the "
                      "board's 25 open cards", f.says)
        self.assertIn("they are the backlog", f.says)

    def test_false_counts_every_unblocked_card(self):
        self.assertEqual(len(run(self.backlog(), ready_needs_sprint=False).ready), 22)

    def test_auto_leaves_a_board_that_does_not_park_its_backlog_in_to_do(self):
        cards = [item(f"#{n}", column="Backlog") for n in range(1, 21)]
        cards += [item("#21", column="To Do", fields=sprint()), item("#22", column="To Do")]
        self.assertEqual(run(board(*cards)).ready, ["#21", "#22"])

    def test_true_without_a_running_sprint_says_so(self):
        a = run(board(item("#1", column="To Do")), ready_needs_sprint=True)
        self.assertEqual(a.ready, ["#1"])
        self.assertIn("no sprint is running", next(x for x in a.findings if x.rule == "ready").says)

    def test_a_wrong_value_is_named(self):
        with self.assertRaisesRegex(ValueError, "ready_needs_sprint"):
            run(board(item("#1")), ready_needs_sprint="sometimes")


class People(unittest.TestCase):
    def test_the_modes(self):
        self.assertEqual([home.people_mode(settings(people=v)) for v in (False, "names", True)], ["off", "names", "all"])
        with self.assertRaisesRegex(ValueError, "people"):
            home.people_mode(settings(people="everyone"))

    def test_names_turns_on_no_load(self):
        cards = [item(f"#{n}", column="In Progress", assignees=["kim"]) for n in range(1, 5)]
        self.assertIn("load", rules_of(run(board(*cards), people=True, person_wip=2)))
        self.assertNotIn("load", rules_of(run(board(*cards), people="names", person_wip=2)))

    def test_names_keeps_the_reading_scrubbed(self):
        from helpers import TempHome
        from hearthwood import reading
        with TempHome() as t:
            b = home.add_board("work", "github", "o/r", h=t.h)
            p = b.dir / "board.toml"
            p.write_text(p.read_text().replace("people = false", 'people = "names"'))
            b = home.BoardHome("work", t.h)
            brd = board(item("#1", assignees=["zoltana"], body="Ask zoltana about this."))
            d = reading.prepare(b, brd, facts.Analysis(brd, b.settings).run(), {})
            text = (d / "items" / "1.md").read_text()
            self.assertNotIn("zoltana", text)
            self.assertIn("Ask someone about this.", text)


if __name__ == "__main__":
    unittest.main()

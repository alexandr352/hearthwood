import unittest

from helpers import PullRequest, board, item, settings

from hearthwood import facts, search, snapshot


def run(b, **rules):
    return facts.Analysis(b, settings(**rules)).run()


def rules_of(a):
    return {f.rule for f in a.findings}


def finding(a, rule):
    return next(f for f in a.findings if f.rule == rule)


class Ready(unittest.TestCase):
    def test_ready_needs_every_dependency_finished(self):
        a = run(board(item("#1", column="Done", state="closed", close_reason="completed"),
                      item("#2", blocked_by=["#1"]), item("#3")))
        self.assertEqual(a.ready, ["#2", "#3"])

    def test_in_review_is_not_finished(self):
        a = run(board(item("#1", column="In Review"), item("#2", blocked_by=["#1"])))
        self.assertNotIn("#2", a.ready)
        self.assertIn("waits-on-review", rules_of(a))

    def test_a_blocking_label_blocks(self):
        a = run(board(item("#1", labels=["needs:decision"])))
        self.assertEqual(a.ready, [])
        self.assertIn("labelled needs:decision", finding(a, "blocked").says)

    def test_a_goal_is_not_work(self):
        a = run(board(item("#1", children=["#2"]), item("#2", parent="#1")))
        self.assertEqual(a.ready, ["#2"])

    def test_goals_in_flight_lead(self):
        a = run(board(item("#5"), item("#9", parent="#1"), item("#1", column="In Progress", children=["#9"])))
        self.assertEqual(a.ready, ["#9", "#5"])

    def test_the_boards_order_wins_over_numbers(self):
        a = run(board(item("#2", fields={"rank": 2}), item("#7", fields={"rank": 1})))
        self.assertEqual(a.ready, ["#7", "#2"])


class Blocked(unittest.TestCase):
    def test_an_abandoned_blocker_is_high(self):
        a = run(board(item("#1", state="closed", column=None, close_reason="not_planned"), item("#2", blocked_by=["#1"])))
        f = finding(a, "blocked")
        self.assertEqual(f.severity, "high")
        self.assertIn("never finish", f.says)

    def test_a_parked_blocker_is_named(self):
        a = run(board(item("#1", column="Backlog"), item("#2", blocked_by=["#1"])))
        self.assertIn("blocked-by-parked", rules_of(a))

    def test_an_unknown_blocker_is_not_assumed_done(self):
        a = run(board(item("#2", blocked_by=["#77"])))
        self.assertEqual(a.ready, [])
        self.assertIn("not in the snapshot", finding(a, "blocked").says)

    def test_a_dependency_written_in_text_counts(self):
        b = board(item("#1", column="In Progress"), item("#2", body="Some work.\n\nDepends on #1 and #404.\n"))
        snapshot.enrich(b)
        self.assertEqual(b.by_key()["#2"].fields["depends_in_text"], ["#1"])
        self.assertIn("#2", b.by_key()["#1"].blocking)
        self.assertNotIn("#2", run(b).ready)

    def test_a_loop_is_found(self):
        a = run(board(item("#1", blocked_by=["#2"]), item("#2", blocked_by=["#1"])))
        self.assertEqual(finding(a, "cycle").severity, "high")


class Honesty(unittest.TestCase):
    def test_stale(self):
        a = run(board(item("#1", column="In Progress", updated="2026-09-01T00:00:00Z")), stale_days=7)
        self.assertEqual(finding(a, "stale").severity, "medium")
        a = run(board(item("#1", column="In Progress", updated="2026-10-08T00:00:00Z")), stale_days=7)
        self.assertNotIn("stale", rules_of(a))

    def test_pull_requests_against_columns(self):
        a = run(board(item("#1", column="In Progress", prs=[PullRequest(1, "merged")]),
                      item("#2", column="In Review"),
                      item("#3", column="Todo", prs=[PullRequest(3, "open")]),
                      item("#4", column="Todo", prs=[PullRequest(4, "open", draft=True)])))
        self.assertTrue({"merged-not-done", "review-without-pr", "pr-not-in-review"} <= rules_of(a))
        self.assertEqual(finding(a, "pr-not-in-review").keys, ["#3"])

    def test_columns_against_state(self):
        a = run(board(item("#1", column="Done"), item("#2", state="closed", column="Todo", close_reason="completed"),
                      item("#3", state="closed", column="Todo", close_reason="completed", column_source="history")))
        self.assertIn("open-in-done", rules_of(a))
        self.assertEqual(finding(a, "closed-not-done").keys, ["#2"])

    def test_hierarchy(self):
        a = run(board(item("#1", state="closed", column="Done", close_reason="completed", children=["#2"]),
                      item("#2", parent="#1"),
                      item("#3", children=["#4", "#5"]), item("#4", state="closed", column="Done", parent="#3"),
                      item("#5", state="closed", column="Done", parent="#3")))
        self.assertIn("parent-closed-children-open", rules_of(a))
        self.assertEqual(finding(a, "children-done-parent-open").keys, ["#3"])

    def test_wip(self):
        a = run(board(item("#1", column="In Progress"), item("#2", column="In Progress")), wip={"In Progress": 1})
        self.assertEqual(finding(a, "wip").evidence["count"], 2)

    def test_duplicates_by_title(self):
        a = run(board(item("#1", title="Search inside notes quickly"), item("#2", title="Search inside all notes quickly"),
                      item("#3", title="Dark mode for the editor")), duplicate_search="titles")
        self.assertEqual(finding(a, "duplicate").keys, ["#1", "#2"])
        self.assertEqual(a.search["method"], "titles")


FILLER = [
    ("Dark mode for the editor", "Offer a dark colour scheme in the editor, following the system setting."),
    ("Export a project as PDF", "Render every chapter to one printable PDF with the cover first."),
    ("Invite a collaborator by email", "Send an invitation link that expires after seven days."),
    ("Keyboard shortcut to duplicate a scene", "Ctrl+D copies the selected scene with its dialogue."),
    ("Show word count per chapter", "A small counter under each chapter heading, updated while typing."),
    ("Autosave drafts every minute", "Write the draft to local storage so a crash loses at most a minute."),
    ("Spellcheck in three languages", "English, German and Spanish dictionaries, chosen per project."),
    ("Billing page shows the next invoice date", "Read the date from the payment provider and show it."),
    ("Archive old projects", "Move projects untouched for a year to an archive list, restorable."),
    ("Tag chapters with colours", "A colour per chapter, shown in the outline and on the canvas."),
]


def filler(start=10):
    return [item(f"#{start + n}", title=t, body=b) for n, (t, b) in enumerate(FILLER)]


TWIN_A = ("Search inside notes is slow on large projects",
          "Typing in the notes search box freezes for seconds once a project has thousands of notes. "
          "Index the notes and debounce the search input.")
TWIN_B = ("Notes search freezes with thousands of notes",
          "On big projects the notes search input hangs while typing. Debounce it and query an index of notes.")


@unittest.skipUnless(search.available(), "this SQLite has no FTS5")
class Duplicates(unittest.TestCase):
    def test_twins_found_by_their_descriptions(self):
        a = run(board(item("#1", title=TWIN_A[0], body=TWIN_A[1]), item("#2", title=TWIN_B[0], body=TWIN_B[1]),
                      *filler()))
        f = finding(a, "duplicate")
        self.assertEqual(f.keys, ["#1", "#2"])
        self.assertEqual(f.evidence["method"], "full-text")
        self.assertEqual(a.search, {"method": "full-text", "searched": 12, "k": 5})
        self.assertEqual(len([x for x in a.findings if x.rule == "duplicate"]), 1)

    def test_a_thin_twin_with_the_same_title_is_still_named(self):
        a = run(board(item("#1", title="Search inside notes", body=TWIN_A[1] + " Results within 200 ms on 5,000 notes."),
                      item("#2", title="Search inside all notes", body="Let people find text in any note."),
                      *filler()))
        f = finding(a, "duplicate")
        self.assertEqual((f.keys, f.evidence["method"]), (["#1", "#2"], "titles"))

    def test_the_title_rule_misses_them(self):
        a = run(board(item("#1", title=TWIN_A[0], body=TWIN_A[1]), item("#2", title=TWIN_B[0], body=TWIN_B[1]),
                      *filler()), duplicate_search="titles")
        self.assertNotIn("duplicate", rules_of(a))

    def test_open_work_that_reads_like_finished_work(self):
        a = run(board(item("#1", title=TWIN_A[0], body=TWIN_A[1], state="closed", column="Done",
                           close_reason="completed", closed="2026-09-20T00:00:00Z"),
                      item("#2", title=TWIN_B[0], body=TWIN_B[1]), *filler()))
        f = finding(a, "done-before")
        self.assertEqual(f.keys, ["#2", "#1"])
        self.assertIn("2026-09-20", f.says)
        self.assertNotIn("duplicate", rules_of(a))

    def test_work_closed_as_not_planned_is_not_done_before(self):
        a = run(board(item("#1", title=TWIN_A[0], body=TWIN_A[1], state="closed", column=None,
                           close_reason="not_planned"),
                      item("#2", title=TWIN_B[0], body=TWIN_B[1]), *filler()))
        self.assertNotIn("done-before", rules_of(a))

    def test_items_the_board_already_ties_are_not_named(self):
        a = run(board(item("#1", title=TWIN_A[0], body=TWIN_A[1], children=["#2"]),
                      item("#2", title=TWIN_B[0], body=TWIN_B[1], parent="#1"), *filler()))
        self.assertNotIn("duplicate", rules_of(a))
        self.assertIn("#1 ", a.similar_markdown().split("#2 | ")[1].split("\n")[0])
        self.assertIn("(linked)", a.similar_markdown())

    def test_similar_md_says_how_many_were_searched(self):
        a = run(board(item("#1", title=TWIN_A[0], body=TWIN_A[1]), item("#2", title=TWIN_B[0], body=TWIN_B[1]),
                      *filler()))
        md = a.similar_markdown()
        self.assertIn("the 5 of 12 items", md)
        self.assertIn("CANDIDATES", md)
        self.assertTrue(md.splitlines()[4].startswith("#1 | #2 "))
        self.assertIn("full text", a.to_markdown())

    def test_a_match_is_against_the_item_itself(self):
        b = board(item("#1", title=TWIN_A[0], body=TWIN_A[1]), item("#2", title=TWIN_B[0], body=TWIN_B[1]), *filler())
        with search.Index(b.items) as index:
            hits = index.similar(b.items[0], k=3)
        self.assertEqual(hits[0][0], "#2")
        self.assertNotIn("#1", [k for k, _ in hits])
        self.assertTrue(all(0 < m <= 1 for _, m in hits))


class NoFts5(unittest.TestCase):
    def test_falls_back_to_titles_and_says_so(self):
        real = search.available
        search.available = lambda: False
        try:
            a = run(board(item("#1", title="Search inside notes quickly"),
                          item("#2", title="Search inside all notes quickly")))
        finally:
            search.available = real
        self.assertEqual(finding(a, "duplicate").keys, ["#1", "#2"])
        self.assertIn("no FTS5", a.to_markdown())
        self.assertIn("not searched", a.similar_markdown())


class People(unittest.TestCase):
    def test_off_by_default(self):
        b = board(*[item(f"#{n}", column="In Progress", assignees=["sam"]) for n in range(5)])
        self.assertNotIn("load", rules_of(run(b, person_wip=2)))

    def test_load_when_turned_on(self):
        b = board(*[item(f"#{n}", column="In Progress", assignees=["sam"]) for n in range(5)])
        f = finding(run(b, people=True, person_wip=2), "load")
        self.assertIn("not about the person", f.says)

    def test_assignees_stay_out_of_item_files_by_default(self):
        it = item("#1", assignees=["sam"])
        self.assertNotIn("sam", facts.item_markdown(it, people=False))
        self.assertIn("sam", facts.item_markdown(it, people=True))


class Ids(unittest.TestCase):
    def test_a_finding_keeps_its_id_across_reads(self):
        b1 = board(item("#1", state="closed", column=None, close_reason="not_planned"), item("#2", blocked_by=["#1"]))
        b2 = board(item("#1", state="closed", column=None, close_reason="not_planned"), item("#2", blocked_by=["#1"]),
                   item("#3"))
        self.assertEqual(finding(run(b1), "blocked").id, finding(run(b2), "blocked").id)

    def test_markdown_carries_earlier_verdicts(self):
        a = run(board(item("#2", blocked_by=["#77"])))
        fid = finding(a, "blocked").id
        md = a.to_markdown({fid: {"verdict": "disagree", "why": "it is known to be done"}})
        self.assertIn('earlier verdict: disagree — "it is known to be done"', md)


if __name__ == "__main__":
    unittest.main()

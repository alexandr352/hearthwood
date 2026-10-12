import json
import unittest

from helpers import DEMO, TempHome, board, item, settings

from hearthwood import criteria, facts, home, reading
from hearthwood.adapters import github, markdown
from hearthwood.model import Board, Comment
from test_reading import demo


def thread(*rows):
    return [Comment(at=at, author=who, body=text) for at, who, text in rows]


class GitHub(unittest.TestCase):
    def test_the_newest_comments_are_read_with_their_count(self):
        from test_github import FakeGitHub, issue
        n = issue(1)
        n["comments"] = {"totalCount": 31, "nodes": [
            {"createdAt": "2026-10-08T00:00:00Z", "url": "u2", "body": "Later.", "author": {"login": "kim"}},
            {"createdAt": "2026-10-02T00:00:00Z", "url": "u1", "body": "Earlier.", "author": None}]}
        fake = FakeGitHub([[n]], [[]])
        it = github.read_board("t", "o/r", token="T", transport=fake).by_key()["#1"]
        self.assertEqual(it.comments, 31)
        self.assertEqual([(c.body, c.author) for c in it.thread], [("Earlier.", ""), ("Later.", "kim")])
        self.assertIn("comments(last: 20)", fake.queries[0]["query"])


class Markdown(unittest.TestCase):
    def test_a_comments_heading_ends_the_description(self):
        b = markdown.read_board("demo", DEMO)
        it = b.by_key()["LAN-7"]
        self.assertNotIn("Comments", it.body)
        self.assertEqual(it.comments, 2)
        self.assertEqual([(c.at, c.author) for c in it.thread],
                         [("2026-09-16T00:00:00Z", "sam"), ("2026-09-18T00:00:00Z", "sam")])
        self.assertIn("offline sync", it.thread[-1].body)

    def test_a_comment_needs_no_author(self):
        body, rows = markdown.split_comments("Text.\n\n## Comments\n\n### 2026-10-01\nFirst.\n\n### 2026-10-02 kim\nSecond.\n")
        self.assertEqual(body.strip(), "Text.")
        self.assertEqual([(c.author, c.body) for c in rows], [("", "First."), ("kim", "Second.")])

    def test_a_snapshot_keeps_the_thread(self):
        b = markdown.read_board("demo", DEMO)
        again = Board.from_dict(json.loads(b.to_json()))
        self.assertEqual(again.by_key()["LAN-7"].thread[0].author, "sam")


class ItemFile(unittest.TestCase):
    def it(self, **kw):
        return item("#5", comments=kw.pop("comments", 2), assignees=["lee"], thread=thread(
            ("2026-10-01T09:00:00Z", "kim", "Waiting on the API. cc @lee"),
            ("2026-10-08T15:30:00Z", "lee", "The API is live, @Kim.")), **kw)

    def test_people_off_hides_who_wrote_and_who_was_mentioned(self):
        it = self.it()
        b = board(it)
        text = facts.item_markdown(it, False, None, facts.board_logins(b))
        self.assertIn("## Comments", text)
        self.assertIn("The API is live, @someone.", text)
        self.assertIn("cc @someone", text)
        for login in ("kim", "Kim", "lee"):
            self.assertNotIn(login, text)

    def test_people_on_shows_them(self):
        text = facts.item_markdown(self.it(), True, None, {"kim", "lee"})
        self.assertIn("· kim", text)
        self.assertIn("@lee", text)

    def test_comments_after_the_last_decision_are_new(self):
        text = facts.item_markdown(self.it(), False, "2026-10-05T00:00:00Z", {"kim", "lee"})
        self.assertIn("last decided about this item on 2026-10-05", text)
        self.assertEqual(text.count("· NEW"), 1)
        self.assertIn("2026-10-08 15:30 · someone · NEW", text)

    def test_nothing_is_new_before_any_decision(self):
        text = facts.item_markdown(self.it(), False, None, set())
        self.assertNotIn("NEW", text)
        self.assertIn("has not decided anything about this item yet", text)

    def test_a_cut_thread_says_so(self):
        text = facts.item_markdown(self.it(comments=7), False, None, set())
        self.assertIn("The last 2 of 7; the 5 before them were not read.", text)

    def test_newest_first(self):
        text = facts.item_markdown(self.it(), True, None, set())
        self.assertLess(text.index("The API is live"), text.index("Waiting on the API"))

    def test_a_bare_login_is_hidden_too_but_not_inside_a_word(self):
        out = facts.without_people("ask kim; kimono stays; ok-kim stays; @Kim; al", {"kim", "al"})
        self.assertEqual(out, "ask someone; kimono stays; ok-kim stays; @someone; al")

    def test_logins_include_the_authors_of_comments(self):
        self.assertEqual(facts.board_logins(board(self.it())), {"kim", "lee"})


class Decisions(unittest.TestCase):
    def test_the_last_decision_is_per_item(self):
        with TempHome() as t:
            home.append_jsonl(criteria.verdicts_path(t.h), {"at": "2026-10-01T00:00:00Z", "board": "t", "keys": ["#1", "#2"]})
            home.append_jsonl(criteria.verdicts_path(t.h), {"at": "2026-10-04T00:00:00Z", "board": "t", "keys": ["#2"]})
            home.append_jsonl(criteria.verdicts_path(t.h), {"at": "2026-10-09T00:00:00Z", "board": "u", "keys": ["#1"]})
            self.assertEqual(criteria.last_decided(t.h, "t"), {"#1": "2026-10-01T00:00:00Z", "#2": "2026-10-04T00:00:00Z"})

    def test_board_md_counts_comments_and_the_new_ones(self):
        it = item("#1", comments=3, thread=thread(("2026-10-02T00:00:00Z", "a", "x"), ("2026-10-06T00:00:00Z", "a", "y")))
        b = board(it)
        a = facts.Analysis(b, settings()).run()
        line = [x for x in facts.board_index(b, a, {"#1": "2026-10-03T00:00:00Z"}).splitlines() if x.startswith("#1 |")][0]
        self.assertIn("| 3 (1 new) |", line)


class Reading(unittest.TestCase):
    def test_a_verdict_older_than_a_comment_is_flagged(self):
        with TempHome() as t:
            b, board_, a, d = demo(t)
            f = next(f for f in a.findings if "LAN-7" in f.keys)
            criteria.record(t.h, b, d, f.id, "disagree", why="parked on purpose")
            rows = home.read_jsonl(criteria.verdicts_path(t.h))
            rows[-1]["at"] = "2026-09-17T00:00:00Z"            # before sam's second comment
            criteria.verdicts_path(t.h).write_text("".join(json.dumps(r) + "\n" for r in rows))
            d2 = reading.prepare(b, board_, a, criteria.latest_by_target(t.h, b.name))
            facts_md = (d2 / "facts.md").read_text()
            self.assertIn("since that verdict, new comments on LAN-7 (1)", facts_md)
            self.assertIn("- LAN-7: 1 new comment since your last decision on it (2026-09-17)", facts_md)
            item_md = (d2 / "items" / "LAN-7.md").read_text()
            self.assertEqual(item_md.count("· NEW"), 1)
            self.assertNotIn("sam", item_md)
            self.assertIn("@someone and I agreed", item_md)
            self.assertIn("read them before you judge the item", reading.mission(d2))

    def test_a_comment_author_named_in_the_answer_is_refused(self):
        devs = reading.check({"summary": "sam is slow.", "attention": [], "questions": [], "proposals": []},
                             {"#1"}, set(), facts.board_logins(board(item("#1", thread=thread(("2026-10-01T00:00:00Z", "sam", "x"))))))
        self.assertTrue(any("names people (sam)" in d for d in devs))


if __name__ == "__main__":
    unittest.main()

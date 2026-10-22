import contextlib
import io
import json
import os
import stat
import sys
import unittest
from unittest import mock

from helpers import DEMO, TempHome

from hearthwood import cli, credentials, home
from hearthwood.adapters import markdown


def manager(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(list(argv))
    return rc, buf.getvalue()


class Flow(unittest.TestCase):
    def test_the_whole_road_on_the_demo_board(self):
        with TempHome() as t:
            self.assertEqual(manager("connect", "markdown", str(DEMO), "--board", "demo")[0], 0)
            self.assertIn("manager read", manager("next")[1])
            rc, text = manager("read")
            self.assertEqual(rc, 0)
            self.assertIn("20 items", text)
            rc, text = manager("analyze")
            self.assertEqual(rc, 0, text)
            self.assertIn("A1", text)
            self.assertIn("review", manager("next")[1])
            rc, text = manager("show", "A1")
            self.assertEqual(rc, 0)
            fid = json.loads(next((t.h / "boards" / "demo" / "analyses").iterdir()).joinpath("facts.json").read_text())["findings"][0]["id"]
            rc, text = manager("verdict", fid, "disagree", "--why", "LAN-18 is fine, see \"Rich text toolbar\"",
                               "--rule", "A blocker closed as not planned means the blocked work needs a new plan.")
            self.assertEqual(rc, 0, text)
            self.assertIn("criterion added", text)
            rc, text = manager("verdict", "Q1", "--answer", "No, only merged work counts.")
            self.assertEqual(rc, 0, text)
            rc, text = manager("approve", "P1", "--why", "yes")
            self.assertIn("does not write to your board", text)
            self.assertIn("approved", manager("status")[1])
            crit = (t.h / "criteria.md").read_text()
            self.assertIn("needs a new plan", crit)
            rc, text = manager("share")
            shared = next((t.h / "share").glob("*.md")).read_text()
            self.assertIn("needs a new plan", shared)
            self.assertNotIn("LAN-18", shared)
            self.assertNotIn("Rich text toolbar", shared)
            page = (t.h / "log.html").read_text()
            self.assertIn("What needs attention", page)
            self.assertIn("approved", page)

    def test_facts_only_calls_no_model(self):
        with TempHome() as t:
            manager("connect", "markdown", str(DEMO), "--board", "demo")
            rc, _ = manager("analyze", "--facts-only")
            self.assertEqual(rc, 0)
            self.assertEqual(t.calls(), [])

    def test_review_records_and_offers_a_rule(self):
        with TempHome() as t:
            manager("connect", "markdown", str(DEMO), "--board", "demo")
            manager("analyze")
            answers = iter(["d", "the queue is being reviewed today", "In review for a day is normal here.", "q"])
            with mock.patch("builtins.input", lambda *_: next(answers)):
                rc, text = manager("review")
            self.assertEqual(rc, 0)
            rows = home.read_jsonl(t.h / "verdicts.jsonl")
            self.assertEqual((rows[0]["target"], rows[0]["verdict"]), ("A1", "disagree"))
            self.assertIn("In review for a day is normal here.", (t.h / "criteria.md").read_text())

    def test_two_boards_must_be_named(self):
        with TempHome():
            manager("connect", "markdown", str(DEMO), "--board", "a")
            manager("connect", "markdown", str(DEMO), "--board", "b")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                rc, _ = manager("read")
            self.assertEqual(rc, 2)
            self.assertIn("-b <board>", err.getvalue())
            self.assertEqual(manager("read", "-b", "b")[0], 0)


class Tokens(unittest.TestCase):
    def test_a_token_is_kept_private_and_never_printed(self):
        with TempHome() as t:
            with mock.patch.object(sys, "stdin", io.StringIO("ghp_secretvalue123\n")):
                rc, text = manager("connect", "github", "--board", "gh", "--repo", "o/r", "--token-stdin")
            self.assertEqual(rc, 0)
            self.assertNotIn("secretvalue", text)
            b = home.resolve_board("gh")
            p = credentials.token_path(b)
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(p.parent).st_mode), 0o700)
            self.assertEqual(credentials.load_token(b)[0], "ghp_secretvalue123")

    def test_a_pasted_sentence_is_refused(self):
        with TempHome():
            with mock.patch.object(sys, "stdin", io.StringIO("not a token at all\n")):
                rc, text = manager("connect", "github", "--board", "gh", "--repo", "o/r", "--token-stdin")
            self.assertEqual(rc, 2)
            self.assertIn("no spaces", text)


class Markdown(unittest.TestCase):
    def test_front_matter(self):
        meta, body = markdown.parse("---\nkey: X-1\nlabels: [a, b]  # two\nblocked_by: []\n---\nText.\n")
        self.assertEqual(meta, {"key": "X-1", "labels": ["a", "b"], "blocked_by": []})
        self.assertEqual(body, "Text.\n")

    def test_the_demo_board(self):
        b = markdown.read_board("demo", DEMO)
        k = b.by_key()
        self.assertEqual(b.columns, ["Backlog", "Todo", "In Progress", "In Review", "Done"])
        self.assertEqual(k["LAN-11"].state, "open")
        self.assertEqual(k["LAN-19"].close_reason, "not_planned")
        self.assertIn("LAN-4", k["LAN-3"].blocking)


if __name__ == "__main__":
    unittest.main()


class DemoAfterARealBoard(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name                # a real board: any folder of tickets but the demo's own

    def test_outside_a_terminal_it_says_how(self):
        with TempHome() as t:
            manager("connect", "demo")
            rc, text = manager("connect", "markdown", self.folder, "--board", "real")
            self.assertEqual(rc, 0)
            self.assertIn("The demo board (demo) is still connected", text)
            self.assertIn("to remove it: manager disconnect demo", text)
            self.assertTrue((t.h / "boards" / "demo").exists())

    def test_in_a_terminal_it_asks_and_removes(self):
        with TempHome() as t:
            manager("connect", "demo")
            with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", return_value=""):
                rc, text = manager("connect", "markdown", self.folder, "--board", "real")
            self.assertIn("demo board demo removed", text)
            self.assertFalse((t.h / "boards" / "demo").exists())
            self.assertTrue((t.h / "boards" / "real").exists())

    def test_asked_once_only(self):
        with TempHome() as t:
            manager("connect", "demo")
            manager("connect", "markdown", self.folder, "--board", "real")
            rc, text = manager("connect", "markdown", self.folder, "--board", "second")
            self.assertNotIn("still connected", text)

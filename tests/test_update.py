import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import TempHome

from hearthwood import cli, home

FAKE_UV = """#!/bin/sh
echo "$@" >> "{log}"
case "$1 $2" in
  "tool dir") echo "{tools}" ;;
  "tool upgrade") exit {code} ;;
esac
"""


def manager(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cli.main(list(argv))
    return code, buf.getvalue()


class Update(unittest.TestCase):
    def fake(self, receipt=None, code=0):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        tools = d / "tools"
        (tools / "hearthwood").mkdir(parents=True)
        if receipt:
            (tools / "hearthwood" / "uv-receipt.toml").write_text(receipt)
        uv = d / "bin" / "uv"
        uv.parent.mkdir()
        uv.write_text(FAKE_UV.format(log=d / "log", tools=tools, code=code))
        uv.chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{uv.parent}{os.pathsep}{old}"
        self.addCleanup(os.environ.__setitem__, "PATH", old)
        return d / "log"

    def test_installed_from_github_it_upgrades(self):
        log = self.fake('[tool]\nrequirements = [{ name = "hearthwood", git = "https://github.com/alexandr352/hearthwood" }]\n')
        code, text = manager("update")
        self.assertEqual(code, 0, text)
        self.assertIn("tool upgrade hearthwood", log.read_text())
        self.assertIn("untouched", text)

    def test_installed_from_a_folder_it_says_how_to_switch(self):
        log = self.fake('[tool]\nrequirements = [{ name = "hearthwood", directory = "/x/hearthwood-main" }]\n')
        code, text = manager("update")
        self.assertEqual(code, 1)
        self.assertIn("uv tool install --force --python-preference only-managed git+https://github.com/alexandr352/hearthwood", text)
        self.assertNotIn("upgrade", log.read_text())

    def test_not_a_uv_install(self):
        self.fake(receipt=None)
        code, text = manager("update")
        self.assertNotEqual(code, 0)
        self.assertIn("uv tool install --python-preference only-managed git+https://github.com/alexandr352/hearthwood", text)

    def test_a_failed_upgrade_is_said(self):
        self.fake('requirements = [{ name = "hearthwood", git = "https://x" }]\n', code=3)
        self.assertNotEqual(manager("update")[0], 0)


class Disconnect(unittest.TestCase):
    def test_it_removes_the_board_and_its_sign_in_and_keeps_the_verdicts(self):
        from hearthwood import criteria, jira_auth
        with TempHome() as t:
            manager("connect", "demo")
            manager("analyze", "--facts-only")
            b = home.BoardHome("demo", t.h)
            jira_auth.save_grant(b, {"access_token": "A"})          # any sign-in file goes with it
            home.append_jsonl(criteria.verdicts_path(t.h), {"at": "2026-10-12T00:00:00Z", "board": "demo", "keys": []})
            code, text = manager("disconnect", "demo")             # not a terminal: refuses without --yes
            self.assertNotEqual(code, 0)
            self.assertTrue(b.dir.exists())
            code, text = manager("disconnect", "demo", "--yes")
            self.assertEqual(code, 0, text)
            self.assertIn("1 snapshot, 1 analysis, and its sign-in", text)
            self.assertFalse(b.dir.exists())
            self.assertFalse(jira_auth.grant_path(b).exists())
            self.assertTrue(criteria.verdicts_path(t.h).exists())
            self.assertNotIn("demo", (t.h / "log.html").read_text().split("<main>")[1][:4000])

    def test_an_unknown_board(self):
        with TempHome():
            self.assertNotEqual(manager("disconnect", "nope", "--yes")[0], 0)


class Model(unittest.TestCase):
    def test_set_and_show_the_model(self):
        with TempHome() as t:
            self.assertEqual(manager("model", "reading", "sonnet")[0], 0)
            self.assertEqual(manager("model", "spirit", "opus")[0], 0)
            cfg = home.config(t.h)
            self.assertEqual((cfg["models"]["analyst"], cfg["models"]["spirit"]), ("sonnet", "opus"))
            self.assertIn("reading: sonnet", manager("model")[1])
            self.assertIn("[reading]", (t.h / "config.toml").read_text())       # the rest of the file is kept


class Demo(unittest.TestCase):
    def test_the_demo_ships_inside_the_package(self):
        with TempHome() as t:
            code, _ = manager("connect", "demo")
            self.assertEqual(code, 0)
            b = home.BoardHome("demo", t.h)
            self.assertTrue((Path(b.where) / "LAN-7.md").exists())
            self.assertEqual(manager("analyze", "--facts-only")[0], 0)


if __name__ == "__main__":
    unittest.main()

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

FENCE = helpers.ROOT / "src" / "hearthwood" / "fence.py"


def decide(policy, tool, tool_input, cwd):
    p = subprocess.run([sys.executable, str(FENCE)], input=json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": cwd}),
                       capture_output=True, text=True, env=dict(os.environ, HEARTHWOOD_FENCE_POLICY=json.dumps(policy)))
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]


class Analyst(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "a"
        self.root.mkdir()
        self.p = {"mode": "analyst", "root": str(self.root)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_its_folder(self):
        self.assertEqual(decide(self.p, "Read", {"file_path": str(self.root / "facts.md")}, str(self.root)), "allow")
        self.assertEqual(decide(self.p, "Grep", {"pattern": "x"}, str(self.root)), "allow")

    def test_nothing_else(self):
        self.assertEqual(decide(self.p, "Read", {"file_path": "/etc/passwd"}, str(self.root)), "deny")
        self.assertEqual(decide(self.p, "Read", {"file_path": "../x"}, str(self.root)), "deny")
        self.assertEqual(decide(self.p, "Bash", {"command": "ls"}, str(self.root)), "deny")
        self.assertEqual(decide(self.p, "Write", {"file_path": str(self.root / "x")}, str(self.root)), "deny")
        self.assertEqual(decide(self.p, "WebFetch", {"url": "https://x"}, str(self.root)), "deny")


class Spirit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = Path(self.tmp.name)
        (self.h / "spirit" / "memory").mkdir(parents=True)
        self.p = {"mode": "spirit", "home": str(self.h)}
        self.cwd = str(self.h / "spirit")

    def tearDown(self):
        self.tmp.cleanup()

    def d(self, tool, ti):
        return decide(self.p, tool, ti, self.cwd)

    def test_manager_commands(self):
        self.assertEqual(self.d("Bash", {"command": "manager status"}), "allow")
        self.assertEqual(self.d("Bash", {"command": 'manager verdict A1 agree --why "fine; ok"'}), "allow")

    def test_one_command_only(self):
        for cmd in ("manager status && rm -rf ~", "manager status | tee x", "manager status > x", "ls",
                    "manager $(whoami)", "manager status\nrm x", "manager chat"):
            self.assertEqual(self.d("Bash", {"command": cmd}), "deny", cmd)

    def test_no_tokens(self):
        self.assertEqual(self.d("Bash", {"command": "manager connect token --board x"}), "deny")
        self.assertEqual(self.d("Read", {"file_path": str(self.h / "credentials" / "x.token")}), "deny")

    def test_reads_home_writes_memory(self):
        self.assertEqual(self.d("Read", {"file_path": str(self.h / "criteria.md")}), "allow")
        self.assertEqual(self.d("Read", {"file_path": "/etc/hosts"}), "deny")
        self.assertEqual(self.d("Write", {"file_path": str(self.h / "spirit" / "memory" / "a.md")}), "allow")
        self.assertEqual(self.d("Write", {"file_path": str(self.h / "criteria.md")}), "deny")

    def test_no_policy_denies(self):
        p = subprocess.run([sys.executable, str(FENCE)], input="{}", capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if k != "HEARTHWOOD_FENCE_POLICY"})
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()

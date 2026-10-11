"""How a spirit session is started (`manager chat`): its own doctrine, behind the fence."""

import json
import os
import shutil
import sys
from pathlib import Path

from . import claude, fence, home

TOOLS = ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "TodoWrite"]


def manager_bin_dir():
    """The folder holding the `manager` command, so the spirit can run it."""
    found = shutil.which("manager")
    if found:
        return str(Path(found).parent)
    beside = Path(sys.executable).parent          # a virtual environment keeps its scripts here
    if (beside / "manager").exists():
        return str(beside)
    return str(Path(sys.argv[0]).resolve().parent)


def launch(h=None):
    """(argv tail, env) for a spirit session: fenced, with only its own doctrine."""
    h = h or home.home_dir()
    sdir = h / "spirit"
    settings = fence.settings_for()
    settings["claudeMdExcludes"] = claude.doctrine_excludes(sdir)
    policy = {"mode": "spirit", "home": str(h), "log": str(sdir / "fence.log")}
    env = dict(os.environ, HEARTHWOOD_FENCE_POLICY=json.dumps(policy), HEARTHWOOD_HOME=str(h))
    env["PATH"] = manager_bin_dir() + os.pathsep + env.get("PATH", "")
    env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    args = ["--settings", json.dumps(settings), "--setting-sources", "project", "--strict-mcp-config",
            "--tools", ",".join(TOOLS), "--add-dir", str(h)]
    return args, env

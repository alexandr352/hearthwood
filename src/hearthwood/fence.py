#!/usr/bin/env python3
"""The fence: a PreToolUse hook that every tool call of a hearthwood session passes.

Default-deny, and any error inside the fence denies. It keeps an honest session in its lane;
it is a guard rail, not a sandbox.

Modes (HEARTHWOOD_FENCE_POLICY carries the policy as JSON):
  analyst   the reading: reads the analysis folder it was started in, nothing else, no shell
  spirit    talks with you: reads the home (never credentials/), writes its own memory,
            runs one `manager <command>` at a time
"""

import json
import os
import re
import shlex
import sys
import time

POLICY = {}
ALWAYS_OK = {"TodoWrite", "StructuredOutput"}
SECRET_NAMES = re.compile(r"(^|/)(credentials|\.ssh|\.gnupg|\.aws|\.netrc|\.git-credentials|\.config/gh|"
                          r"\.claude/\.credentials\.json|\.claude\.json)(/|$)")


def log(decision, tool, reason, detail=""):
    path = POLICY.get("log")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\t%s\t%.300s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    POLICY.get("mode", "?"), decision, tool, reason, str(detail).replace("\n", " ")))
    except OSError:
        pass


def decide(decision, tool, reason, detail=""):
    log(decision, tool, reason, detail)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def allow(tool, reason="allowed", detail=""):
    decide("allow", tool, reason, detail)


def deny(tool, reason, detail=""):
    decide("deny", tool, "hearthwood fence: " + reason, detail)


def norm(path, cwd):
    p = os.path.expanduser(os.path.expandvars(str(path)))
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def under(path, roots):
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def file_tool_path(ti):
    return ti.get("file_path") or ti.get("path") or ti.get("notebook_path") or ""


def check_analyst(tool, ti, cwd):
    root = os.path.realpath(POLICY["root"])
    if tool in ("Read", "Grep", "Glob", "LS"):
        p = file_tool_path(ti)
        p = norm(p, cwd) if p else os.path.realpath(cwd)
        if not under(p, [root]):
            deny(tool, "the reading reads its analysis folder only", p)
        allow(tool, "read")
    deny(tool, f"{tool} is not available to the reading: it reads, it does not act")


def unquoted_newline(cmd):
    quote = None
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            return True
    return False


def check_spirit(tool, ti, cwd):
    home = os.path.realpath(POLICY["home"])
    memory = os.path.join(home, "spirit", "memory")
    if tool in ("Read", "Grep", "Glob", "LS"):
        p = file_tool_path(ti)
        p = norm(p, cwd) if p else os.path.realpath(cwd)
        if SECRET_NAMES.search(p):
            deny(tool, f"{p} holds secrets")
        if not under(p, [home]):
            deny(tool, "the spirit reads the hearthwood home only")
        allow(tool, "read")
    if tool in ("Edit", "Write", "MultiEdit"):
        p = norm(file_tool_path(ti) or "", cwd)
        if not under(p, [memory]):
            deny(tool, "the spirit writes only its memory; everything else changes through `manager` commands")
        allow(tool, "memory")
    if tool == "Bash":
        cmd = ti.get("command", "").strip()
        if "`" in cmd or "$(" in cmd:
            deny(tool, "no command substitution, not even inside quotes", cmd)
        if unquoted_newline(cmd):
            deny(tool, "one command at a time", cmd)
        try:
            lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>()")
            lex.whitespace_split = True
            words = list(lex)
            argv = shlex.split(cmd)
        except ValueError:
            deny(tool, "the command does not parse", cmd)
        if any(w and set(w) <= set(";&|<>()") for w in words):
            deny(tool, "one command at a time, no pipes, redirects or chains", cmd)
        if argv and os.path.basename(argv[0]) == "manager" and len(argv) > 1 and argv[1] not in ("chat",):
            if argv[1] == "connect":
                deny(tool, "connecting a board takes a token: the person runs `manager connect` themselves", cmd)
            allow(tool, "manager command", cmd)
        deny(tool, "the spirit runs `manager <command>`, nothing else", cmd)
    if tool == "Skill":
        allow(tool, "skill")
    deny(tool, f"{tool} is not available to the spirit")


def main():
    global POLICY
    raw = os.environ.get("HEARTHWOOD_FENCE_POLICY")
    if not raw:
        decide("deny", "?", "hearthwood fence: no policy was given, so nothing is allowed")
    POLICY = json.loads(raw)
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = str(data.get("cwd") or os.getcwd())
    if tool in ALWAYS_OK:
        allow(tool, "harness-internal")
    mode = POLICY.get("mode")
    if mode == "analyst":
        check_analyst(tool, ti, cwd)
    elif mode == "spirit":
        check_spirit(tool, ti, cwd)
    deny(tool, f"unknown fence mode {mode!r}")


def settings_for():
    """The --settings JSON that attaches this fence to every tool call."""
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(os.path.abspath(__file__))}"
    return {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]},
            "disableAllHooks": False}


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log("deny", "?", f"fence internal error: {e.__class__.__name__}: {e}")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": "hearthwood fence: internal error, denied"}}))
        sys.exit(0)

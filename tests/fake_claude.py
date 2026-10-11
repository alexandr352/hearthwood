#!/usr/bin/env python3
"""A stand-in for the Claude Code CLI: answers a reading from the analysis folder it runs in.

Flags are files in $FAKE_STATE, each used once: bad-once (an answer missing its keys),
names-person (an answer naming an assignee), unknown-key (an answer citing a key not on the
board), always-bad (every answer broken), fail (the call errors).
"""
import json
import os
import sys
import uuid
from pathlib import Path

argv = sys.argv[1:]
prompt = sys.stdin.read()
state = Path(os.environ["FAKE_STATE"])
state.mkdir(parents=True, exist_ok=True)
resume = argv[argv.index("--resume") + 1] if "--resume" in argv else None
sid = resume or str(uuid.uuid4())
totals_p = state / "totals.json"
totals = json.loads(totals_p.read_text()) if totals_p.exists() else {}
totals[sid] = round(totals.get(sid, 0) + 0.10, 4)
totals_p.write_text(json.dumps(totals))
with open(state / "calls.jsonl", "a") as f:
    f.write(json.dumps({"cwd": os.getcwd(), "resume": resume, "prompt": prompt[:3000], "argv": argv,
                        "policy": os.environ.get("HEARTHWOOD_FENCE_POLICY")}) + "\n")


def flag(name, keep=False):
    p = state / name
    if p.exists():
        if not keep:
            p.unlink()
        return True
    return False


def envelope(result, is_error=False, code=0):
    print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}))
    print(json.dumps({"type": "result", "result": result, "is_error": is_error, "session_id": sid,
                      "total_cost_usd": totals[sid], "usage": {"input_tokens": 10, "output_tokens": 5},
                      "modelUsage": {"fake-model": {}}}))
    sys.exit(code)


if "--include-partial-messages" in argv:
    # the spirit on the page: a streamed answer with one command run on the way
    print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}))
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "manager next"}}]}}))
    for part in ("Look at ", "LAN-3 first", ": it gates LAN-4."):
        print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                                                          "delta": {"type": "text_delta", "text": part}}}))
    print(json.dumps({"type": "result", "result": "Look at LAN-3 first: it gates LAN-4.", "is_error": False,
                      "session_id": sid, "total_cost_usd": totals[sid]}))
    sys.exit(0)

if flag("fail"):
    print("boom", file=sys.stderr)
    sys.exit(1)

facts = json.loads(Path("facts.json").read_text())
board = Path("board.md").read_text()
keys = [line.split(" | ")[0] for line in board.splitlines() if " | " in line and not line.startswith("key ")]
finding = next((f for f in facts["findings"] if f["rule"] != "ready"), facts["findings"][0])
answer = {
    "summary": "Offline mode is close but its queue waits on review. One item is blocked forever.",
    "attention": [{"title": "Merge the queue to unblock the replay", "keys": finding["keys"][:2],
                   "finding_ids": [finding["id"]], "why": "Two items wait on it.",
                   "next_step": "Review and merge the queue.", "confidence": "high"}],
    "questions": [{"question": "Do you count In Review as done for planning?", "for": "you", "keys": []}],
    "proposals": [{"action": "link", "keys": keys[:2], "change": f"Link {keys[0]} to {keys[1]}.", "why": "They are one piece of work."}],
}
if flag("always-bad", keep=True) or flag("bad-once"):
    envelope(json.dumps({"summary": "half an answer"}) + "\nand some words after")
if flag("names-person"):
    answer["attention"][0]["why"] = "sam is holding it up."
if flag("unknown-key"):
    answer["attention"][0]["keys"] = ["#999999"]
envelope("Here is my reading:\n" + json.dumps(answer))

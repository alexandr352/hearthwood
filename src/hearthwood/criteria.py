"""Your verdicts, your criteria, and what you choose to share.

Every finding, every point of attention and every proposal can be answered: agree, disagree,
right finding for the wrong reason, or not now, with one line of why. Those lines are the most
valuable thing hearthwood collects: they say how the person looking after a board actually judges it. A
verdict you want to keep as a standing rule goes into criteria.md, which every reading reads
first and which outranks the reading's own defaults.
"""

import json
import re
from pathlib import Path

from . import home

VERDICTS = ("agree", "disagree", "wrong-reason", "not-now")


def verdicts_path(h):
    return h / "verdicts.jsonl"


def all_verdicts(h, board=None):
    rows = home.read_jsonl(verdicts_path(h))
    return [r for r in rows if board is None or r.get("board") == board]


def latest_by_target(h, board):
    """The newest verdict per finding id (stable across reads while the same items are involved)."""
    out = {}
    for r in all_verdicts(h, board):
        if r.get("kind") == "finding":
            out[r["target"]] = r
    return out


def last_decided(h, board):
    """{item key: when the person last decided anything about it}: the newest verdict, answer or approval
    whose point names the item. Comments after that moment are what the person has not weighed yet."""
    out = {}
    for r in all_verdicts(h, board):
        for k in r.get("keys") or []:
            if r.get("at", "") > out.get(k, ""):
                out[k] = r["at"]
    return out


def resolve(d, target):
    """(kind, rule, keys, text) for a target in analysis folder `d`: a finding id, A<n>, Q<n> or P<n>."""
    facts = json.loads((d / "facts.json").read_text(encoding="utf-8"))
    for f in facts["findings"]:
        if f["id"] == target:
            return "finding", f["rule"], f["keys"], f["title"]
    reading = None
    try:
        reading = json.loads((d / "reading.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    m = re.match(r"^([AQP])(\d+)$", target)
    if m and reading:
        n = int(m.group(2)) - 1
        lists = {"A": ("attention", "title"), "Q": ("questions", "question"), "P": ("proposals", "change")}
        name, field = lists[m.group(1)]
        rows = reading.get(name) or []
        if 0 <= n < len(rows):
            r = rows[n]
            return name, None, r.get("keys", []), r.get(field, "")
    raise ValueError(f"{target!r} is not a finding id, A<n>, Q<n> or P<n> of analysis {d.name}")


def record(h, b, d, target, verdict, why="", answer=""):
    kind, rule, keys, text = resolve(d, target)
    if kind == "questions":
        if not answer.strip():
            raise ValueError("a question takes an answer: --answer \"...\"")
        verdict = "answered"
    elif verdict not in VERDICTS:
        raise ValueError(f"a verdict is one of {', '.join(VERDICTS)}")
    row = {"at": home.now_iso(), "board": b.name, "analysis": d.name, "target": target,
           "kind": "finding" if kind == "finding" else kind, "rule": rule, "keys": keys, "about": text,
           "verdict": verdict, "why": why.strip(), "answer": answer.strip()}
    home.append_jsonl(verdicts_path(h), row)
    return row


def add_rule(h, text, source=""):
    text = " ".join(text.split())
    if not text:
        raise ValueError("an empty rule")
    p = h / "criteria.md"
    body = p.read_text(encoding="utf-8") if p.exists() else ""
    if "## My rules" not in body:
        body = body.rstrip() + "\n\n## My rules\n\n"
    line = f"- {text}" + (f"  <!-- {home.now_iso()[:10]}, from {source} -->" if source else f"  <!-- {home.now_iso()[:10]} -->")
    p.write_text(body.rstrip() + "\n" + line + "\n", encoding="utf-8")
    return line


def set_proposal(d, pid, status, why=""):
    p = d / "proposals.json"
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    for r in rows:
        if r["id"] == pid:
            r["status"], r["why_status"], r["at"] = status, why.strip(), home.now_iso()
            p.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
            return r
    raise ValueError(f"no proposal {pid} in analysis {d.name}")


def tallies(h, board=None):
    """{rule: {verdict: count}} over finding verdicts."""
    out = {}
    for r in all_verdicts(h, board):
        if r.get("kind") == "finding":
            out.setdefault(r.get("rule") or "?", {}).setdefault(r["verdict"], 0)
            out[r.get("rule") or "?"][r["verdict"]] += 1
    return out


KEY_RE = re.compile(r"(?<![\w/])(#\d+|[A-Z][A-Z0-9]+-\d+)\b|[\w.-]+/[\w.-]+#\d+")


def scrub(text):
    """Item keys out, quoted titles out: what is shared is how you judge, not what is on your board."""
    text = KEY_RE.sub("[item]", text or "")
    return re.sub(r"\"[^\"]{6,}\"", "\"[title]\"", text)


def share(h):
    """Write share/criteria-<date>.md for the person to read and, if they choose, send."""
    crit = (h / "criteria.md").read_text(encoding="utf-8") if (h / "criteria.md").exists() else ""
    lines = ["# How I judge a board", "",
             "Prepared by hearthwood for you to read before you send it to anyone. It holds your criteria and "
             "your reasons; item numbers and quoted titles are replaced by [item] and [title]. Edit or delete "
             "anything you would not say in public.", "", "## My criteria", "",
             re.sub(r"<!--.*?-->", "", crit).strip(), "", "## How often I agreed with each kind of finding", "",
             "rule | agree | disagree | wrong reason | not now", "--- | --- | --- | --- | ---"]
    for rule, t in sorted(tallies(h).items()):
        lines.append(f"{rule} | {t.get('agree', 0)} | {t.get('disagree', 0)} | {t.get('wrong-reason', 0)} | {t.get('not-now', 0)}")
    lines += ["", "## My reasons, as I wrote them", ""]
    for r in all_verdicts(h):
        if r.get("why") or r.get("answer"):
            label = r.get("rule") or r.get("kind")
            lines.append(f"- [{label}, {r['verdict']}] " + scrub(r.get("why") or r.get("answer")))
    out = h / "share" / f"criteria-{home.now_iso()[:10]}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out

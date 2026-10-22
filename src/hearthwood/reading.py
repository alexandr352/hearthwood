"""`manager analyze`: the facts, then one reading of them by Claude.

The reading is one Claude Code session started in the analysis folder. It is handed the facts
and your criteria whole, may read and search the board's items in that folder, and nothing
else: no shell, no network, no writing. Its answer is one JSON object that the program checks
(the contract below). A broken answer goes back to the same session with what is wrong named;
after `reconsider` tries the reading is recorded as broken and the facts stand on their own.
"""

import json
import re
from pathlib import Path

from . import claude, criteria, facts, fence, home, sprints

ACTIONS = ("comment", "link", "unlink", "move", "label", "close", "reopen", "split", "merge", "ask")
ASKS = ("you", "scope", "product", "engineering")
CONFIDENCE = ("high", "medium", "low")
TOP = ("summary", "attention", "questions", "proposals")

SCHEMA = """{
  "summary": "two to four plain sentences: the state of the board and what matters most now",
  "attention": [
    {"title": "short, what needs attention",
     "keys": ["#12"],                       // the items it is about; every key must be on the board
     "finding_ids": ["stale-1a2b3c"],       // the facts it rests on, by id; [] only if it rests on items you read
     "why": "why it matters for the flow of work, citing what you read",
     "next_step": "the one thing the person looking after this board would do about it",
     "confidence": "high | medium | low"}
  ],                                         // at most 10, most important first
  "questions": [
    {"question": "what you could not settle from the board", "for": "you | scope | product | engineering",
     "keys": ["#12"]}
  ],                                         // at most 5; "you" = a question about how this person wants
                                             // the board judged, so their answer can become a criterion
  "proposals": [
    {"action": "comment | link | unlink | move | label | close | reopen | split | merge | ask",
     "keys": ["#12"], "change": "exactly what would change on the board", "why": "why"}
  ]                                          // at most 10; nothing is written: the person approves or not
}"""


def check(obj, keys, finding_ids, logins=(), people=False):
    """A list of deviations; empty when the answer keeps its contract."""
    if not isinstance(obj, dict):
        return ["the answer is not one JSON object"]
    dev = []
    extra = [k for k in obj if k not in TOP]
    if extra:
        dev.append(f"unknown keys {extra}: the answer has exactly {', '.join(TOP)}")
    s = obj.get("summary")
    if not (isinstance(s, str) and s.strip() and len(s) <= 1200):
        dev.append('"summary" is two to four plain sentences, at most 1200 characters')

    def keys_ok(where, ks, need):
        if not isinstance(ks, list) or (need and not ks):
            dev.append(f'{where}: "keys" is a list of item keys' + (" with at least one" if need else ""))
            return
        unknown = [k for k in ks if k not in keys]
        if unknown:
            dev.append(f"{where}: {unknown} are not on this board; cite only keys that are (board.md lists them)")

    att = obj.get("attention")
    if not isinstance(att, list) or len(att) > 10:
        dev.append('"attention" is a list of at most 10 entries')
        att = []
    for n, a in enumerate(att, 1):
        w = f"attention[{n}]"
        if not isinstance(a, dict):
            dev.append(f"{w} is an object")
            continue
        for k in ("title", "why", "next_step"):
            if not (isinstance(a.get(k), str) and a[k].strip()):
                dev.append(f'{w}: "{k}" is missing')
        if isinstance(a.get("title"), str) and len(a["title"]) > 140:
            dev.append(f'{w}: "title" is at most 140 characters')
        keys_ok(w, a.get("keys"), True)
        fids = a.get("finding_ids", [])
        if not isinstance(fids, list):
            dev.append(f'{w}: "finding_ids" is a list')
        else:
            bad = [f for f in fids if f not in finding_ids]
            if bad:
                dev.append(f"{w}: {bad} are not finding ids of these facts; use the ids exactly as facts.md writes them")
        if a.get("confidence") not in CONFIDENCE:
            dev.append(f'{w}: "confidence" is high, medium or low')
    qs = obj.get("questions", [])
    if not isinstance(qs, list) or len(qs) > 5:
        dev.append('"questions" is a list of at most 5')
        qs = []
    for n, q in enumerate(qs, 1):
        w = f"questions[{n}]"
        if not isinstance(q, dict) or not (isinstance(q.get("question"), str) and q["question"].strip()):
            dev.append(f'{w}: "question" is missing')
            continue
        if q.get("for") not in ASKS:
            dev.append(f'{w}: "for" is one of {", ".join(ASKS)}')
        keys_ok(w, q.get("keys", []), False)
    ps = obj.get("proposals", [])
    if not isinstance(ps, list) or len(ps) > 10:
        dev.append('"proposals" is a list of at most 10')
        ps = []
    for n, p in enumerate(ps, 1):
        w = f"proposals[{n}]"
        if not isinstance(p, dict):
            dev.append(f"{w} is an object")
            continue
        if p.get("action") not in ACTIONS:
            dev.append(f'{w}: "action" is one of {", ".join(ACTIONS)}')
        for k in ("change", "why"):
            if not (isinstance(p.get(k), str) and p[k].strip()):
                dev.append(f'{w}: "{k}" is missing')
        keys_ok(w, p.get("keys"), True)
    if not people and logins:
        text = json.dumps(obj, ensure_ascii=False)
        named = sorted({l for l in logins if len(l) >= 3 and re.search(r"(?<![\w-])@?" + re.escape(l) + r"(?![\w-])", text)})
        if named:
            dev.append(f"the answer names people ({', '.join(named)}): speak of the work, not of who does it; "
                       "this board has people = false")
    return dev


def deviation_message(devs):
    return "\n".join(["DEVIATION: your answer broke its contract. Fix exactly this and answer again with ONE JSON "
                      "object, nothing around it:"] + [f"- {d}" for d in devs])


def prepare(b, board, analysis, verdicts, view="all-all"):
    """Write the analysis folder the reading works in. Returns its path. `view` narrows what the reading is
    given to the cards in that view (sprints.VIEWS); facts.json stays whole, for the page."""
    d, n = b.analyses / home.stamp(), 1
    while d.exists():
        n += 1
        d = b.analyses / f"{home.stamp()}-{n}"
    (d / "items").mkdir(parents=True)
    people = home.people_mode(b.settings) == "all"     # "names" is the page's, never the reading's
    days = int(b.settings["rules"].get("recent_days", 60))
    keep = None if view == "all-all" else sprints.view_keys(board.items, view, board.fetched_at, days)
    label = sprints.VIEW_LABELS[view].format(days=days)
    (d / "view.json").write_text(json.dumps({"view": view, "label": label, "cards": len(keep) if keep is not None else len(board.items),
                                             "of": len(board.items)}), encoding="utf-8")
    decided = criteria.last_decided(b.home, b.name)
    logins = facts.board_logins(board)
    (d / "facts.json").write_text(json.dumps(analysis.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    (d / "facts.md").write_text(analysis.to_markdown(verdicts, decided, keep, label), encoding="utf-8")
    (d / "board.md").write_text(facts.board_index(board, analysis, decided, keep), encoding="utf-8")
    (d / "similar.md").write_text(analysis.similar_markdown(keep), encoding="utf-8")
    for it in board.items + board.outside:
        (d / "items" / facts.item_file_name(it.key)).write_text(
            facts.item_markdown(it, people, decided.get(it.key), logins), encoding="utf-8")
    crit = b.home / "criteria.md"
    (d / "criteria.md").write_text(crit.read_text(encoding="utf-8") if crit.exists() else "(none yet)\n", encoding="utf-8")
    (d / "CLAUDE.md").write_text(home.doctrine("analyst", "CLAUDE.md"), encoding="utf-8")
    return d


def mission(d):
    return "\n".join([
        "READING",
        "",
        "Read the facts of this board and your person's criteria below, then answer with ONE JSON object in "
        "exactly this shape (the comments are guidance, not part of the answer):",
        "",
        SCHEMA,
        "",
        "board.md in this folder lists the items, one per line (in a reading of one view: the cards in view and the "
        "ones they link to); items/<number>.md holds one item whole. Read "
        "what you need to be sure; cite only keys that exist. An item's file ends with its comments, newest first; "
        "read them before you judge the item. similar.md lists, for every open item, the items "
        "that read most like it: candidates for duplicates and for work already done, never verdicts.",
        "",
        "=== criteria.md (the person's own criteria; they outrank your defaults) ===",
        (d / "criteria.md").read_text(encoding="utf-8"),
        "",
        "=== facts.md (whole) ===",
        (d / "facts.md").read_text(encoding="utf-8"),
    ])


def run(b, d, board, analysis, claude_bin=None, model=None):
    """Run the reading in folder `d`. Returns (reading dict or None, list of call records, status line)."""
    cfg = home.config(b.home)
    claude_bin = claude_bin or cfg["claude"]["bin"]
    model = model or cfg["models"]["analyst"]
    tries = int(cfg["reading"].get("reconsider", 3))
    max_turns = int(cfg["reading"].get("max_turns", 30))
    timeout = int(cfg["timeouts"].get("reading", 900))
    keys = set(board.lookup())
    fids = {f.id for f in analysis.findings}
    logins = facts.board_logins(board)
    people = home.people_mode(b.settings) == "all"
    settings = fence.settings_for()
    settings["claudeMdExcludes"] = claude.doctrine_excludes(d)
    policy = {"mode": "analyst", "root": str(d), "log": str(d / "fence.log")}
    costs = claude.CostLedger(b.home / "costs.json")
    prompt, session, records, devs, answer = mission(d), None, [], [], None
    (d / "mission.md").write_text(prompt, encoding="utf-8")
    for attempt in range(1, tries + 1):
        res = claude.run(claude_bin=claude_bin, cwd=d, prompt=prompt, model=model, timeout=timeout,
                         label=f"reading-{attempt}", costs=costs, resume=session, tools=["Read", "Grep", "Glob"],
                         settings=settings, setting_sources=["project"], max_turns=max_turns,
                         env_extra={"HEARTHWOOD_FENCE_POLICY": json.dumps(policy)})
        rec = res.record()
        rec.update(board=b.name, analysis=d.name, at=home.now_iso())
        records.append(rec)
        home.append_jsonl(d / "calls.jsonl", rec)
        home.append_jsonl(b.home / "runs.jsonl", {k: rec.get(k) for k in (
            "at", "board", "analysis", "label", "model", "seconds", "cost_usd", "cost_basis", "error", "walled")})
        if not res.ok:
            (d / "reading-failed.txt").write_text(res.error or "the call failed", encoding="utf-8")
            return None, records, f"the reading did not run: {res.error}" + (" (a usage limit)" if res.walled else "")
        session = res.session_id or session
        (d / f"answer-{attempt}.txt").write_text(res.text, encoding="utf-8")
        answer = claude.extract_json(res.text)
        devs = check(answer, keys, fids, logins, people)
        if not devs:
            (d / "reading.json").write_text(json.dumps(answer, indent=1, ensure_ascii=False), encoding="utf-8")
            write_proposals(d, answer)
            return answer, records, f"read in {attempt} {'try' if attempt == 1 else 'tries'}"
        prompt = deviation_message(devs)
        if not session:
            prompt = mission(d) + "\n\nYOUR PREVIOUS ANSWER, WHOLE:\n" + res.text + "\n\n" + prompt
    (d / "reading-broken.json").write_text(json.dumps({"deviations": devs, "last_answer": answer}, indent=1,
                                                      ensure_ascii=False), encoding="utf-8")
    return None, records, f"the reading broke its contract {tries} times; the facts stand alone ({'; '.join(devs[:3])})"


def write_proposals(d, reading):
    rows = []
    for n, p in enumerate(reading.get("proposals") or [], 1):
        rows.append(dict(p, id=f"P{n}", status="proposed"))
    (d / "proposals.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")


def load(d):
    d = Path(d)
    try:
        return json.loads((d / "reading.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


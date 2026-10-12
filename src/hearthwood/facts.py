"""The facts of a board, computed by plain code before any model reads it.

Each rule below is a small, checkable judgment about the WORK on a board: what is ready,
what is blocked and by what, what has stopped moving, where the board says one thing and the
pull requests say another. A rule never guesses. Where something cannot be known (an issue
outside the snapshot, a column that was never set) it says so, and what is not known is never
counted as fine.

The rules are documented one by one in docs/how-it-works.md. Hearthwood looks at the work, not
at the people: the only rule about people (`load`) is off unless the board turns it on.
"""

import hashlib
import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from . import search

SEVERITIES = ("high", "medium", "low", "info")
STOP = {"a", "an", "the", "to", "of", "in", "on", "for", "and", "or", "with", "is", "be", "by", "at", "as",
        "from", "into", "it", "its", "this", "that", "when", "not", "no"}


@dataclass
class Finding:
    rule: str
    severity: str
    title: str
    keys: list
    says: str
    evidence: dict = field(default_factory=dict)
    id: str = ""

    def __post_init__(self):
        if not self.id:
            digest = hashlib.sha1("|".join(sorted(self.keys)).encode()).hexdigest()[:6]
            self.id = f"{self.rule}-{digest}"


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def days_between(a, b):
    return (b - a).total_seconds() / 86400.0


def count_of(n, word="item"):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _num(key):
    m = re.search(r"(\d+)$", key)
    return int(m.group(1)) if m else 0


class Analysis:
    def __init__(self, board, settings, now=None):
        self.board = board
        self.s = settings
        self.rules = settings["rules"]
        self.cols = settings["columns"]
        self.now = now or parse_ts(board.fetched_at) or datetime.now(timezone.utc)
        self.items = board.by_key()
        self.findings = []
        self.search = {}
        self.similar = {}

    # --- reading an item ----------------------------------------------------

    def cols_role(self, column):
        for r in ("done", "review", "active", "startable", "parked"):
            if column in self.cols.get(r, []):
                return r
        return "other"

    def role(self, it):
        if it.column is None:
            return None
        for r in ("done", "review", "active", "startable", "parked"):
            if it.column in self.cols.get(r, []):
                return r
        return "other"

    def blocking_labels(self, it):
        import fnmatch
        pats = self.rules.get("blocking_labels", [])
        return [l for l in it.labels if any(fnmatch.fnmatchcase(l, p) for p in pats)]

    def deps(self, it):
        return list(dict.fromkeys(list(it.blocked_by) + list(it.fields.get("depends_in_text", []))))

    def dep_state(self, key):
        """done | in-review | open | parked | abandoned | unknown, for a dependency's key."""
        d = self.items.get(key)
        if d is None:
            return "unknown"
        if d.state == "closed":
            return "abandoned" if d.close_reason in ("not_planned", "duplicate") else "done"
        r = self.role(d)
        if r == "done":
            return "done"
        if r == "review":
            return "in-review"
        if r == "parked":
            return "parked"
        return "open"

    def why_blocked(self, d, st):
        if st == "in-review":
            return f"{d} is in review, not yet merged or accepted"
        if st == "open":
            return f"{d} is not finished"
        if st == "parked":
            return f"{d} is parked ({self.items[d].column}), so this waits on work nobody plans to do now"
        if st == "abandoned":
            return f"{d} was closed as {self.items[d].close_reason.replace('_', ' ')}, so it will never finish"
        return f"{d} is not in the snapshot (closed long ago, or elsewhere): unknown, so counted as not done"

    def rank(self, it):
        r = it.fields.get("rank")
        return (0, r) if isinstance(r, int) else (1, _num(it.key))

    def open_items(self):
        return [i for i in self.board.items if i.state == "open"]

    def is_goal(self, it):
        """An item with open sub-items is a goal: it is judged by its sub-items, not as work itself."""
        return any(self.items[k].state == "open" for k in it.children if k in self.items)

    def add(self, *a, **kw):
        self.findings.append(Finding(*a, **kw))

    # --- the rules ----------------------------------------------------------

    def run(self):
        self.r_blocked_and_ready()
        self.r_cycles()
        self.r_stale()
        self.r_pull_requests()
        self.r_column_vs_state()
        self.r_hierarchy()
        self.r_wip()
        self.r_duplicates()
        self.r_unplaced()
        self.r_thin()
        if self.rules.get("people"):
            self.r_load()
        self.flow = self.r_flow()
        order = {s: n for n, s in enumerate(SEVERITIES)}
        self.findings.sort(key=lambda f: (order.get(f.severity, 9), f.rule, f.keys[:1]))
        return self

    def r_blocked_and_ready(self):
        ready, waiting_on_merge = [], []
        for it in self.open_items():
            role = self.role(it)
            if role not in ("startable", "active"):
                continue
            reasons, worst = [], None
            for d in self.deps(it):
                st = self.dep_state(d)
                if st == "done":
                    continue
                reasons.append((d, st))
            labels = self.blocking_labels(it)
            if not reasons and not labels:
                if role == "startable" and not self.is_goal(it):
                    ready.append(it)
                continue
            parts = []
            for d, st in reasons:
                parts.append(self.why_blocked(d, st))
            if labels:
                parts.append("labelled " + ", ".join(labels))
            states = {st for _, st in reasons}
            if states & {"abandoned"}:
                worst = "high"
            elif states & {"parked", "open", "unknown"} or labels:
                worst = "medium"
            else:
                worst = "low"
            if states == {"in-review"} and not labels:
                waiting_on_merge.append((it.key, [d for d, _ in reasons]))
                continue
            rule = "blocked-by-parked" if "parked" in states else "blocked"
            self.add(rule, worst, f"{it.key} in {it.column} is blocked", [it.key] + [d for d, _ in reasons],
                     f"{it.key} \"{it.title}\" ({it.column}): " + "; ".join(parts) + ".",
                     {"column": it.column, "blockers": dict(reasons), "labels": labels})
        if waiting_on_merge:
            keys = [k for k, _ in waiting_on_merge]
            lines = [f"{k} waits on {', '.join(ds)}" for k, ds in waiting_on_merge]
            self.add("waits-on-review", "low", f"{count_of(len(keys))} " + ("waits" if len(keys) == 1 else "wait") + " only on work in review",
                     keys + sorted({d for _, ds in waiting_on_merge for d in ds}),
                     "In review is not finished: these start when what they depend on is merged or accepted. "
                     + "; ".join(lines) + ".", {"pairs": dict(waiting_on_merge)})
        # Ready, goals in flight first: an item under an active parent (followed 3 deep) leads.
        def depth_under_active(it):
            k, depth = it.parent, 1
            while k and depth <= 3:
                p = self.items.get(k)
                if p is None:
                    return 0
                if p.state == "open" and self.role(p) == "active":
                    return 4 - depth
                k, depth = p.parent, depth + 1
            return 0
        ready.sort(key=lambda it: (-depth_under_active(it), self.rank(it)))
        self.ready = [it.key for it in ready]
        ranked = any(isinstance(it.fields.get("rank"), int) for it in ready)
        if ready:
            self.add("ready", "info", f"{count_of(len(ready))} " + ("is" if len(ready) == 1 else "are") + " ready to start", self.ready,
                     ("Ready means: in a column where work waits, every dependency finished, no blocking label. "
                      "Order: items under a parent that is in progress first, then "
                      + ("the board's own order." if ranked else "by number, because the board's order was not readable.")),
                     {"order": self.ready, "board_order": ranked})

    def r_cycles(self):
        graph = {it.key: [d for d in self.deps(it) if d in self.items] for it in self.board.items if it.state == "open"}
        seen, cycles = set(), []

        def visit(k, path):
            if k in path:
                cyc = path[path.index(k):]
                norm = tuple(sorted(cyc))
                if norm not in seen:
                    seen.add(norm)
                    cycles.append(cyc + [k])
                return
            if len(path) > 50:
                return
            for d in graph.get(k, []):
                visit(d, path + [k])

        for k in graph:
            visit(k, [])
        for c in cycles:
            self.add("cycle", "high", "a dependency loop", sorted(set(c)),
                     "These items wait on each other, so none of them can start: " + " -> ".join(c) + ".")

    def r_stale(self):
        limit = float(self.rules.get("stale_days", 7))
        for it in self.open_items():
            role = self.role(it)
            if role not in ("active", "review") or self.is_goal(it):
                continue
            t = parse_ts(it.updated)
            if not t:
                continue
            age = days_between(t, self.now)
            if age >= limit:
                self.add("stale", "medium" if age >= 2 * limit else "low", f"{it.key} has not moved in {int(age)} days",
                         [it.key], f"{it.key} \"{it.title}\" has been {('in ' + it.column) if it.column else 'open'} with "
                         f"no update for {int(age)} days (the limit is {int(limit)}).", {"days": round(age, 1)})

    def r_pull_requests(self):
        if not self.board.prs_read:
            return
        for it in self.open_items():
            role = self.role(it)
            merged = [p for p in it.prs if p.state == "merged"]
            live = [p for p in it.prs if p.state == "open"]
            if merged and role not in ("done",):
                self.add("merged-not-done", "medium", f"{it.key} has a merged pull request but is still open",
                         [it.key], f"{it.key} \"{it.title}\" is {it.column or 'open'} while "
                         + ", ".join(f"PR {p.number}" if p.number else "its pull request" for p in merged)
                         + " is merged. Either the work is finished and the card did not follow, or the PR was only part of it.")
            if role == "review" and not live and not merged:
                self.add("review-without-pr", "medium", f"{it.key} is in review with no open pull request", [it.key],
                         f"{it.key} \"{it.title}\" sits in {it.column}, but no open or merged pull request is linked "
                         "to it. In review with nothing to review is usually a card that did not move back. (A pull "
                         "request is linked when it says \"Closes {it.key}\" or is linked by hand.)")
            if role in ("startable", "active") and [p for p in live if not p.draft]:
                self.add("pr-not-in-review", "low", f"{it.key} has an open pull request but sits in {it.column}",
                         [it.key], f"{it.key} \"{it.title}\" has an open pull request ready for review, yet the "
                         f"board shows it in {it.column}.")

    def r_column_vs_state(self):
        known = ("board", "file")
        for it in self.board.items:
            role = self.role(it)
            if it.state == "closed" and it.close_reason not in ("not_planned", "duplicate") \
                    and role not in (None, "done") and it.column_source in known:
                self.add("closed-not-done", "low", f"{it.key} is closed but shows in {it.column}", [it.key],
                         f"{it.key} \"{it.title}\" is closed as finished, while the board still shows it in {it.column}.")
            if it.state == "open" and role == "done":
                self.add("open-in-done", "medium", f"{it.key} is in {it.column} but still open", [it.key],
                         f"{it.key} \"{it.title}\" sits in {it.column} and is not closed: finished on the board, open "
                         "in the tracker. Anything that depends on it counts it as finished.")

    def r_hierarchy(self):
        for it in self.board.items:
            kids = [self.items[k] for k in it.children if k in self.items]
            if not kids:
                continue
            open_kids = [k for k in kids if k.state == "open"]
            if it.state == "closed" and open_kids:
                self.add("parent-closed-children-open", "medium", f"{it.key} is closed with open sub-items",
                         [it.key] + [k.key for k in open_kids],
                         f"{it.key} \"{it.title}\" is closed while {len(open_kids)} of its sub-items are open: "
                         + ", ".join(k.key for k in open_kids[:12]) + ("..." if len(open_kids) > 12 else "") + ".")
            if it.state == "open" and not open_kids and len(kids) >= 2:
                self.add("children-done-parent-open", "low", f"every sub-item of {it.key} is closed",
                         [it.key], f"All {len(kids)} sub-items of {it.key} \"{it.title}\" are closed and it is still open. "
                         "Finished, or is there work nobody has written down yet?")

    def r_wip(self):
        limits = self.rules.get("wip") or {}
        for col, limit in limits.items():
            here = [i for i in self.open_items() if i.column == col]
            if len(here) > int(limit):
                self.add("wip", "medium", f"{col} holds {len(here)}, the limit is {limit}", [i.key for i in here],
                         f"{len(here)} open items are in {col} against a limit of {limit}: "
                         + ", ".join(i.key for i in here) + ".", {"column": col, "count": len(here), "limit": limit})

    def linked(self, a, b):
        """Two items the board already ties together: parent and sub-item, or a dependency either way."""
        A, B = self.items[a], self.items[b]
        return (A.parent == b or B.parent == a or b in A.children or a in B.children
                or b in self.deps(A) or a in self.deps(B) or b in A.blocking or a in B.blocking)

    def r_duplicates(self):
        """Items that read alike: open twins, and open work that reads like work already finished."""
        if self.rules.get("duplicate_search", "full-text") == "titles" or not search.available():
            why = ("" if self.rules.get("duplicate_search") == "titles"
                   else " (this Python's SQLite has no FTS5, so full-text search is off)")
            self.search = {"method": "titles", "why": why.strip(" ()")}
            return self.r_duplicates_by_title()
        k = int(self.rules.get("duplicate_candidates", 5))
        thr = float(self.rules.get("duplicate_match", 0.5))
        with search.Index(self.board.items) as index:
            self.search = {"method": "full-text", "searched": len(index), "k": k}
            self.similar = {it.key: index.similar(it, k) for it in self.board.items}
        # A pair is named when each item is the other's closest match the board does not already tie to
        # it, and both directions reach `duplicate_match`. Measured on a 728-item board, the looser "each
        # in the other's top k" named 51 pairs at 0.5, most of them clusters of related work; this, 16.
        closest = {}
        for key, hits in self.similar.items():
            free = [(o, m) for o, m in hits if not self.linked(key, o)]
            closest[key] = free[0] if free else (None, 0.0)
        seen = set()
        for it in sorted(self.open_items(), key=lambda i: _num(i.key)):
            other, m = closest[it.key]
            if other is None or closest[other][0] != it.key:
                continue
            pair = tuple(sorted((it.key, other), key=_num))
            both = min(m, closest[other][1])
            if pair in seen or both < thr:
                continue
            seen.add(pair)
            O = self.items[other]
            ev = {"match": both, "method": "full-text"}
            if O.state == "open":
                a, b = (self.items[x] for x in pair)
                self.add("duplicate", "low", f"{a.key} and {b.key} read alike", list(pair),
                         f"{a.key} \"{a.title}\" and {b.key} \"{b.title}\" are each other's closest match by the "
                         f"words of their titles and descriptions (match {both:.2f}). "
                         "The same work twice, or two halves that should name each other?", ev)
            elif O.close_reason not in ("not_planned", "duplicate"):
                self.add("done-before", "low", f"{it.key} reads like {O.key}, already finished", [it.key, O.key],
                         f"{it.key} \"{it.title}\" reads most like {O.key} \"{O.title}\", closed "
                         f"{O.closed[:10] or 'earlier'}, and the other way round (match {both:.2f}). Already done, "
                         "or a follow-up that should say which work it follows?", ev)
        # Nearly the same title is a duplicate however the descriptions differ: a thin card twinning a
        # full one reads weakly against the full one's own words, and the search alone would let it pass.
        for a, b, sim in self.title_twins():
            if (a, b) not in seen and not self.linked(a, b):
                self.add_title_twin(a, b, sim)

    def title_twins(self):
        """[(a, b, similarity)]: open items whose titles share at least `duplicate_similarity` of their words."""
        thr = float(self.rules.get("duplicate_similarity", 0.7))
        words = {}
        for it in self.open_items():
            w = {x for x in re.findall(r"[a-z0-9]+", it.title.lower()) if x not in STOP and len(x) > 1}
            if len(w) >= 3:
                words[it.key] = w
        keys = sorted(words, key=_num)
        out = []
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                inter = len(words[a] & words[b])
                if inter and inter / len(words[a] | words[b]) >= thr:
                    out.append((a, b, round(inter / len(words[a] | words[b]), 2)))
        return out

    def add_title_twin(self, a, b, sim):
        A, B = self.items[a], self.items[b]
        self.add("duplicate", "low", f"{a} and {b} look alike", [a, b],
                 f"{a} \"{A.title}\" and {b} \"{B.title}\" share {int(sim * 100)}% of their title words. "
                 "The same work twice, or two halves that should name each other?",
                 {"similarity": sim, "method": "titles"})

    def r_duplicates_by_title(self):
        for a, b, sim in self.title_twins():
            self.add_title_twin(a, b, sim)

    def r_unplaced(self):
        items = self.open_items()
        nocol = [i for i in items if i.column is None]
        if nocol:
            self.add("no-column", "low", f"{count_of(len(nocol), 'open item')} " + ("has" if len(nocol) == 1 else "have") + " no column", [i.key for i in nocol],
                     f"{count_of(len(nocol), 'open item')} " + ("is" if len(nocol) == 1 else "are") + " on no column of the board"
                     + (" (or their column could not be read)" if any(i.column_source == "none" for i in nocol) else "")
                     + ": " + ", ".join(i.key for i in sorted(nocol, key=lambda i: _num(i.key))[:20])
                     + ("..." if len(nocol) > 20 else "") + ".")
        with_parent = sum(1 for i in self.board.items if i.parent)
        if self.board.items and with_parent / len(self.board.items) >= 0.3:
            orphans = [i for i in items if not i.parent and not i.children and self.role(i) in ("startable", "active")]
            if orphans:
                self.add("no-parent", "low", f"{count_of(len(orphans))} in play " + ("belongs" if len(orphans) == 1 else "belong") + " to no parent", [i.key for i in orphans],
                         f"Most of this board hangs under parents (epics), but {len(orphans)} items waiting or in progress "
                         "belong to none: " + ", ".join(i.key for i in orphans[:20]) + ("..." if len(orphans) > 20 else "")
                         + ". Work under no goal is hard to rank.")

    def r_thin(self):
        thin = [i for i in self.open_items() if self.role(i) in ("startable", "active") and len(i.body.strip()) < 40]
        if thin:
            self.add("thin", "low", f"{count_of(len(thin))} in play " + ("has" if len(thin) == 1 else "have") + " almost no description", [i.key for i in thin],
                     f"{len(thin)} items waiting or in progress have fewer than 40 characters of description: "
                     + ", ".join(i.key for i in thin[:20]) + ("..." if len(thin) > 20 else "") + ".")

    def r_load(self):
        limit = int(self.rules.get("person_wip") or 0)
        held = {}
        for it in self.open_items():
            if self.role(it) in ("active", "review"):
                for a in it.assignees:
                    held.setdefault(a, []).append(it.key)
        for person, keys in sorted(held.items()):
            if limit and len(keys) > limit:
                self.add("load", "medium", f"{person} holds {len(keys)} items in progress or review", keys,
                         f"{person} is carrying {len(keys)} items at once (more than {limit}): {', '.join(keys)}. "
                         "This is about load, not about the person: too much at once slows every item.")

    def r_flow(self):
        """Numbers, not findings: how work moves. Read by the person and the reading alike."""
        now = self.now
        done = [i for i in self.board.items if i.state == "closed" and i.close_reason not in ("not_planned", "duplicate")]
        closed_7 = [i for i in done if (t := parse_ts(i.closed)) and days_between(t, now) <= 7]
        closed_30 = [i for i in done if (t := parse_ts(i.closed)) and days_between(t, now) <= 30]
        cycle = [days_between(a, b) for i in closed_30 if (a := parse_ts(i.created)) and (b := parse_ts(i.closed))]
        by_role = {}
        for i in self.open_items():
            t = parse_ts(i.created)
            if t:
                by_role.setdefault(self.role(i) or "no column", []).append(days_between(t, now))
        dwell = {}
        for i in self.board.items:
            h = i.history
            for a, b in zip(h, h[1:] + [None]):
                start = parse_ts(a["at"])
                end = parse_ts(b["at"]) if b else (parse_ts(i.closed) if i.state == "closed" else None)
                if a["to"] and start and end and self.cols_role(a["to"]) != "done":
                    dwell.setdefault(a["to"], []).append(max(0.0, days_between(start, end)))
        counts = {}
        for i in self.open_items():
            counts[i.column or "(no column)"] = counts.get(i.column or "(no column)", 0) + 1
        med = lambda xs: round(statistics.median(xs), 1) if xs else None
        return {
            "open": len(self.open_items()), "open_by_column": counts,
            "finished_last_7_days": len(closed_7), "finished_last_30_days": len(closed_30),
            "median_days_open_to_finished_30d": med(cycle),
            "median_age_open_by_role": {k: med(v) for k, v in sorted(by_role.items())},
            "median_days_in_column": {k: med(v) for k, v in sorted(dwell.items())},
        }

    # --- output -----------------------------------------------------------------

    def to_dict(self):
        return {"board": self.board.name, "fetched_at": self.board.fetched_at, "notes": self.board.notes,
                "flow": self.flow, "ready": self.ready, "search": self.search,
                "similar": {k: v for k, v in self.similar.items() if self.items[k].state == "open"},
                "findings": [asdict(f) for f in self.findings]}

    def search_line(self):
        s = self.search
        if s.get("method") == "full-text":
            return (f"Duplicates were searched by full text over the title and description of all {s['searched']} "
                    f"items, open and closed; similar.md lists each open item's {s['k']} closest.")
        return "Duplicates were compared by title words only" + (f" ({s['why']})." if s.get("why") else ".")

    def similar_markdown(self):
        """For the reading: every open item's closest matches. Candidates, never verdicts."""
        if not self.similar:
            return "# Items that read alike\n\n(not searched: " + self.search_line() + ")\n"
        k, n = self.search["k"], self.search["searched"]
        out = ["# Items that read alike", "",
               f"For every open item, the {k} of {n} items (open and closed) whose titles and descriptions read most "
               "like it, closest first. match 1.00 = as close as the item is to itself. These are CANDIDATES: most "
               "close matches are related work (the same screen, the same file), not the same work twice. Open both "
               "items before you call two of them duplicates. (linked) = the board already ties the two together.", ""]
        for it in sorted(self.open_items(), key=lambda i: _num(i.key)):
            hits = self.similar.get(it.key) or []
            cells = [f"{o} {m:.2f}" + (" (linked)" if self.linked(it.key, o) else "")
                     + (f" ({self.items[o].state})" if self.items[o].state != "open" else "") for o, m in hits]
            out.append(f"{it.key} | " + (" | ".join(cells) if cells else "-"))
        return "\n".join(out) + "\n"

    def to_markdown(self, verdicts=None, decided=None):
        verdicts, decided = verdicts or {}, decided or {}
        f = self.flow
        out = [f"# Facts of board {self.board.name}", "",
               f"Read {self.board.fetched_at} from {self.board.source} {self.board.where}.", "",
               self.search_line(), ""]
        if self.board.notes:
            out += ["## What could not be read", ""] + [f"- {n}" for n in self.board.notes] + [""]
        out += ["## Flow", "",
                f"- open: {f['open']} ({', '.join(f'{k} {v}' for k, v in f['open_by_column'].items())})",
                f"- finished in the last 7 days: {f['finished_last_7_days']}; last 30 days: {f['finished_last_30_days']}",
                f"- median days from opened to finished (last 30 days): {f['median_days_open_to_finished_30d']}",
                f"- median age of open items by column role: {f['median_age_open_by_role']}",
                f"- median days spent in each column (from status history): {f['median_days_in_column']}", ""]
        out += ["## Findings", "", "Each finding: id, rule, severity, what it says. The person's earlier verdict on the "
                "same finding follows it when there is one.", ""]
        for x in self.findings:
            out.append(f"### {x.id} [{x.rule}, {x.severity}] {x.title}")
            out.append(x.says)
            v = verdicts.get(x.id)
            if v:
                out.append(f"> earlier verdict: {v['verdict']}" + (f" — \"{v['why']}\"" if v.get("why") else ""))
                since = [f"{k} ({n})" for k in x.keys if k in self.items
                         for n in [len(new_comments(self.items[k], v.get("at")))] if n]
                if since:
                    out.append(f"> since that verdict, new comments on {', '.join(since)}: read them before relying on it")
            out.append("")
        talk = []
        for it in sorted(self.open_items(), key=lambda i: _num(i.key)):
            new = new_comments(it, decided.get(it.key))
            if new:
                talk.append(f"- {it.key}: {count_of(len(new), 'new comment')} since your last decision on it "
                            f"({decided[it.key][:10]})")
        out += ["## Comments since your decisions", "",
                "Open items with comments newer than the person's last decision about them. What was decided may "
                "no longer hold; the comments are in items/<number>.md, marked NEW.", ""]
        out += (talk or ["(none)"]) + [""]
        return "\n".join(out)


def board_index(board, analysis, decided=None):
    """One line per item, for the reading to search: key | state | column | type | title | ..."""
    decided = decided or {}
    lines = ["# Every item on the board, one per line", "",
             "key | state | column | type | parent | depends on | pull requests | labels | comments | updated | title",
             ""]
    for it in sorted(board.items, key=lambda i: _num(i.key)):
        deps = analysis.deps(it)
        prs = ",".join(f"{p.number or ''}:{p.state}" for p in it.prs)
        new = len(new_comments(it, decided.get(it.key)))
        talk = str(it.comments or len(it.thread)) + (f" ({new} new)" if new else "")
        lines.append(" | ".join([it.key, it.state + (f"/{it.close_reason}" if it.close_reason else ""),
                                 it.column or "-", it.kind or "-", it.parent or "-", ",".join(deps) or "-",
                                 prs or "-", ",".join(it.labels) or "-", talk, it.updated[:10], it.title]))
    return "\n".join(lines) + "\n"


def new_comments(it, since):
    """The comments of `it` written after `since` (an ISO time); none when nothing was decided about it yet."""
    if not since:
        return []
    return [c for c in it.thread if c.at > since]


def board_logins(board):
    """Every login the board shows: assignees and the authors of comments."""
    return {a for it in board.items for a in list(it.assignees) + [c.author for c in it.thread] if a}


def without_people(text, logins):
    """`text` with every known login made "someone": as an @mention always, and as a bare word from three
    letters up, the words the reading's contract refuses to see in an answer."""
    for login in sorted(logins, key=len, reverse=True):
        at = "@?" if len(login) >= 3 else "@"
        text = re.sub(r"(?<![\w-])(" + at + ")" + re.escape(login) + r"(?![\w-])", r"\1someone", text, flags=re.I)
    return text


def item_file_name(key):
    return re.sub(r"[^A-Za-z0-9._-]", "_", key.lstrip("#")) + ".md"


def item_markdown(it, people, decided_at=None, logins=()):
    head = [f"# {it.key}: {it.title}", "",
            f"- state: {it.state}" + (f" ({it.close_reason})" if it.close_reason else ""),
            f"- column: {it.column or '-'} (from {it.column_source or '-'})",
            f"- type: {it.kind or '-'}", f"- labels: {', '.join(it.labels) or '-'}",
            f"- parent: {it.parent or '-'}; sub-items: {', '.join(it.children) or '-'}",
            f"- blocked by: {', '.join(it.blocked_by) or '-'}; written dependencies: "
            f"{', '.join(it.fields.get('depends_in_text', [])) or '-'}; blocking: {', '.join(it.blocking) or '-'}",
            f"- pull requests: {', '.join(f'{p.number}:{p.state}' for p in it.prs) or '-'}",
            f"- created {it.created[:10]}, updated {it.updated[:10]}, closed {it.closed[:10] or '-'}",
            f"- comments: {it.comments}"]
    if people:
        head.append(f"- assignees: {', '.join(it.assignees) or '-'}")
    if it.history:
        head.append("- column history: " + "; ".join(f"{h['at'][:10]} {h['from'] or '-'} -> {h['to'] or '-'}" for h in it.history))
    out = "\n".join(head) + "\n\n## Description\n\n" + (it.body.strip() or "(empty)") + "\n"
    if it.thread:
        out += _comments_markdown(it, people, decided_at)
    return out if people else without_people(out, logins)


def _comments_markdown(it, people, decided_at):
    shown = len(it.thread)
    lines = ["", "## Comments", ""]
    if it.comments > shown:
        lines.append(f"The last {shown} of {it.comments}; the {it.comments - shown} before them were not read.")
    if decided_at:
        lines.append(f"The person last decided about this item on {decided_at[:10]}. Comments after that are marked NEW: "
                     "they may change what was decided.")
    else:
        lines.append("The person has not decided anything about this item yet.")
    lines += ["Newest first.", ""]
    for c in reversed(it.thread):
        who = (c.author or "someone") if people else "someone"
        new = " · NEW" if decided_at and c.at > decided_at else ""
        when = c.at[:10] if c.at[10:19] in ("", "T00:00:00") else c.at[:16].replace("T", " ")
        lines += [f"### {when} · {who}{new}", "", c.body.strip() or "(empty)", ""]
    return "\n".join(lines).rstrip() + "\n"

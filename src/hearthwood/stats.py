"""The numbers of a board, for the Stats tab: plain code over one snapshot, no model.

Everything here is counted from the snapshot alone. A snapshot holds every open item and the items
closed in the last `closed_days` (board.toml), so a count that reaches further back than that is
marked as short rather than shown as if it were whole.

"Type" is the tracker's issue type, or, when the board sets `[stats] type_labels`, the first label
matching one of those patterns (e.g. "op:*"). A "goal" is an item with sub-items, or one labelled
with a `[stats] goal_labels` pattern, so a goal with nothing under it yet still counts as one.
"""

import fnmatch
from datetime import timedelta

from .facts import days_between, parse_ts

WEEKS = 6
DAYS = 14
AGES = ((7, "under 7 days"), (30, "7 to 30 days"), (90, "30 to 90 days"), (None, "over 90 days"))


def _done(it):
    return it.state == "closed" and it.close_reason not in ("not_planned", "duplicate")


def _dropped(it):
    return it.state == "closed" and it.close_reason in ("not_planned", "duplicate")


def item_type(it, patterns):
    for label in it.labels:
        if any(fnmatch.fnmatchcase(label, p) for p in patterns):
            return label
    return it.kind or "-"


class Stats:
    def __init__(self, board, settings, now=None):
        self.board = board
        self.s = settings
        self.items = board.by_key()
        self.now = now or parse_ts(board.fetched_at)
        st = settings.get("stats", {})
        self.type_patterns = list(st.get("type_labels", []))
        self.goal_patterns = list(st.get("goal_labels", []))
        self.closed_days = int(settings["rules"].get("closed_days", 60))
        self.cols = settings["columns"]

    # --- helpers ---------------------------------------------------------------

    def role(self, it):
        for r in ("done", "review", "active", "startable", "parked"):
            if it.column in self.cols.get(r, []):
                return r
        return None

    def age(self, ts):
        t = parse_ts(ts)
        return days_between(t, self.now) if t else None

    def is_goal(self, it):
        return bool(it.children) or any(fnmatch.fnmatchcase(l, p) for l in it.labels for p in self.goal_patterns)

    def open_items(self):
        return [i for i in self.board.items if i.state == "open"]

    def columns(self):
        """Columns in board order, then any column an open item sits in that the board did not list."""
        order = list(self.board.columns)
        for it in self.open_items():
            c = it.column or "(no column)"
            if c not in order:
                order.append(c)
        return order

    # --- the numbers ----------------------------------------------------------------

    def headline(self):
        op = self.open_items()
        by_role = {}
        for it in op:
            by_role.setdefault(self.role(it), []).append(it)
        last = [i for i in self.board.items if (a := self.age(i.created)) is not None and a <= DAYS]
        closed = [i for i in self.board.items if i.state == "closed" and (a := self.age(i.closed)) is not None and a <= DAYS]
        loose = [i for i in op if not i.parent and not self.is_goal(i)]
        waiting = by_role.get("startable", []) + by_role.get("parked", [])
        wait_cols = {}
        for it in waiting:
            wait_cols[it.column] = wait_cols.get(it.column, 0) + 1
        return {"open": len(op), "waiting": len(waiting), "waiting_by_column": wait_cols,
                "created_14": len(last), "closed_14": len(closed),
                "done_14": sum(1 for i in closed if _done(i)), "dropped_14": sum(1 for i in closed if _dropped(i)),
                "no_goal": len(loose), "active": len(by_role.get("active", [])), "review": len(by_role.get("review", []))}

    def weeks(self):
        """The last WEEKS seven-day windows ending at the snapshot, oldest first."""
        out = []
        for n in range(WEEKS, 0, -1):
            end = self.now - timedelta(days=7 * (n - 1))
            start = end - timedelta(days=7)
            def inside(ts):
                t = parse_ts(ts)
                return t is not None and start < t <= end
            created = sum(1 for i in self.board.items if inside(i.created))
            done = sum(1 for i in self.board.items if _done(i) and inside(i.closed))
            dropped = sum(1 for i in self.board.items if _dropped(i) and inside(i.closed))
            short = days_between(start, self.now) > self.closed_days
            out.append({"from": start.strftime("%b %d"), "to": (end - timedelta(seconds=1)).strftime("%b %d"),
                        "created": created, "done": done, "dropped": dropped, "net": created - done - dropped,
                        "short": short})
        return out

    def goals(self):
        rows, empty = [], []
        for g in self.board.items:
            if not self.is_goal(g):
                continue
            if g.state == "closed" and ((a := self.age(g.closed)) is None or a > 30):
                continue
            kids = [self.items[k] for k in g.children if k in self.items]
            if not g.children:
                if g.state == "open":
                    empty.append(g.key)
                continue
            done = sum(1 for k in kids if _done(k))
            open_ = sum(1 for k in kids if k.state == "open")
            rows.append({"key": g.key, "title": g.title, "state": g.state, "column": g.column, "created": g.created[:10],
                         "cards": len(g.children), "open": open_, "done": done,
                         "unknown": len(g.children) - len(kids),
                         "progress": round(100 * done / (done + open_)) if done + open_ else None,
                         "added_30": sum(1 for k in kids if (a := self.age(k.created)) is not None and a <= 30),
                         "closed_30": sum(1 for k in kids if k.state == "closed" and (a := self.age(k.closed)) is not None and a <= 30),
                         "added_7": sum(1 for k in kids if (a := self.age(k.created)) is not None and a <= 7)})
        rows.sort(key=lambda r: (-r["open"], -r["cards"]))
        return rows, empty

    def types(self):
        cols = self.columns()
        table = {}
        for it in self.open_items():
            t = item_type(it, self.type_patterns)
            row = table.setdefault(t, {c: 0 for c in cols})
            row[it.column or "(no column)"] += 1
        rows = sorted(table.items(), key=lambda kv: -sum(kv[1].values()))
        used = [c for c in cols if any(r[c] for _, r in rows)]
        return used, [(t, [r[c] for c in used], sum(r.values())) for t, r in rows]

    def ages(self):
        buckets = [[label, 0] for _, label in AGES]
        parked_old = 0
        for it in self.open_items():
            a = self.age(it.created)
            if a is None:
                continue
            for n, (limit, _) in enumerate(AGES):
                if limit is None or a < limit:
                    buckets[n][1] += 1
                    break
            if self.role(it) == "parked" and a > 30:
                parked_old += 1
        parked = sum(1 for it in self.open_items() if self.role(it) == "parked")
        return buckets, parked_old, parked

    def days(self):
        out = []
        for n in range(DAYS - 1, -1, -1):
            day = (self.now - timedelta(days=n)).date()
            def on(ts):
                t = parse_ts(ts)
                return t is not None and t.date() == day
            out.append({"day": day.strftime("%a %b %d"),
                        "created": sum(1 for i in self.board.items if on(i.created)),
                        "done": sum(1 for i in self.board.items if _done(i) and on(i.closed)),
                        "dropped": sum(1 for i in self.board.items if _dropped(i) and on(i.closed))})
        return out

    def to_dict(self):
        goals, empty = self.goals()
        cols, types = self.types()
        ages, parked_old, parked = self.ages()
        return {"headline": self.headline(), "weeks": self.weeks(), "goals": goals, "empty_goals": empty,
                "type_columns": cols, "types": types, "ages": ages, "parked_old": parked_old, "parked": parked,
                "days": self.days(), "closed_days": self.closed_days, "fetched_at": self.board.fetched_at}

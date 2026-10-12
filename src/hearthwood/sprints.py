"""Sprints: which sprint a card is in, which sprints are running, and their order.

A board read from Jira carries each card's current sprint in its fields: `sprint` (the name),
`sprint_state` (active | future | closed), `sprint_start`, `sprint_end`, `sprint_goal`. A board
without sprints (GitHub, markdown) has none of these, and everything here is empty for it.

Teams use Jira's sprints two ways: as real time-boxes, and as parking places that are never started
("Groomed", "Ideas"). Jira tells them apart by state and dates, so the order is: the running sprints,
then the coming ones (a start date ahead, or at most PAST_START_DAYS behind; newest first), then the
parking places (no start date, or one long gone by) with the most recently worked-on first, then the
closed ones (newest first).
"""


def sprint_of(fields):
    """The card's sprint as {"name", "state", "start", "end", "goal"}, or None."""
    fields = fields or {}
    name = fields.get("sprint")
    if not name:
        return None
    return {"name": name, "state": fields.get("sprint_state") or "", "start": fields.get("sprint_start") or "",
            "end": fields.get("sprint_end") or "", "goal": fields.get("sprint_goal") or ""}


def _fields(it):
    return it.get("fields") if isinstance(it, dict) else it.fields


PAST_START_DAYS = 30


def ordered(items):
    """Every sprint the items name, once, in board order: running, coming, parking, closed."""
    seen, last = {}, {}
    for it in items:
        s = sprint_of(_fields(it))
        if not s:
            continue
        seen.setdefault(s["name"], s)
        u = (it.get("updated") if isinstance(it, dict) else it.updated) or ""
        last[s["name"]] = max(last.get(s["name"], ""), u)
    now = max(last.values(), default="")
    cutoff = _days_before(now, PAST_START_DAYS)

    def key(s):
        if s["state"] == "active":
            return (0, s["start"], s["name"])
        if s["state"] == "closed":
            return (3, _desc(s["end"] or s["start"]), s["name"])
        if s["start"] and s["start"] >= cutoff:
            return (1, _desc(s["start"]), s["name"])
        return (2, _desc(last.get(s["name"], "")), s["name"])
    return sorted(seen.values(), key=key)


def _days_before(ts, days):
    from datetime import datetime, timedelta, timezone
    try:
        t = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return (t - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _desc(ts):
    """A string that sorts newest first."""
    return "".join(chr(0x10FFFF - ord(c)) for c in ts)


def active_names(items):
    return [s["name"] for s in ordered(items) if s["state"] == "active"]


def active_keys(items):
    """The keys of the cards in a running sprint, finished ones included (done this sprint)."""
    names = set(active_names(items))
    out = set()
    for it in items:
        s = sprint_of(_fields(it))
        if s and s["name"] in names:
            out.add(it["key"] if isinstance(it, dict) else it.key)
    return out


VIEWS = ("sprint-recent", "sprint-all", "all-recent", "all-all")
VIEW_LABELS = {"sprint-recent": "this sprint, cards touched in the last {days} days", "sprint-all": "this sprint",
               "all-recent": "every card touched in the last {days} days", "all-all": "the whole board"}


def view_keys(items, view, fetched_at, recent_days):
    """The keys of the cards in a view: 'sprint-' keeps the running sprint's cards (when there is one),
    '-recent' keeps cards updated within `recent_days` of the read."""
    from .facts import days_between, parse_ts
    if view not in VIEWS:
        raise ValueError(f"a view is one of {', '.join(VIEWS)}")
    scope, time = view.split("-")
    keys = {(it["key"] if isinstance(it, dict) else it.key) for it in items}
    if scope == "sprint":
        inside = active_keys(items)
        if inside:
            keys &= inside
    if time == "recent":
        now = parse_ts(fetched_at)
        def fresh(it):
            t = parse_ts((it.get("updated") if isinstance(it, dict) else it.updated) or "")
            return bool(now and t and days_between(t, now) <= recent_days)
        keys &= {(it["key"] if isinstance(it, dict) else it.key) for it in items if fresh(it)}
    return keys

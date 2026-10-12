"""Sprints: which sprint a card is in, which sprints are running, and their order.

A board read from Jira carries each card's current sprint in its fields: `sprint` (the name),
`sprint_state` (active | future | closed), `sprint_start`, `sprint_end`, `sprint_goal`. A board
without sprints (GitHub, markdown) has none of these, and everything here is empty for it.

Teams use Jira's sprints two ways: as real time-boxes, and as parking places that are never started
("Groomed", "Ideas"). Jira tells them apart by state, so the order is: the running sprints, then the
future ones (by start date, those with none last), then the closed ones (newest first).
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


def ordered(items):
    """Every sprint the items name, once, in board order: active, future, closed."""
    seen = {}
    for it in items:
        s = sprint_of(_fields(it))
        if s and s["name"] not in seen:
            seen[s["name"]] = s
    rank = {"active": 0, "future": 1, "": 1, "closed": 2}
    def key(s):
        r = rank.get(s["state"], 1)
        if r == 2:
            return (r, "~" if not s["end"] else "", _desc(s["end"]), s["name"])
        return (r, s["start"] or "~", s["name"])
    return sorted(seen.values(), key=key)


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

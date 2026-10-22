"""The board as hearthwood holds it: one shape for every tracker.

An adapter (GitHub, a folder of markdown files, later Jira) reads a tracker and returns a
Board. Everything after that, the facts, the reading, the log page, works on this shape
alone and never asks the tracker again.
"""

import json
from dataclasses import asdict, dataclass, field


@dataclass
class PullRequest:
    number: int
    state: str              # open | closed | merged
    draft: bool = False
    url: str = ""


@dataclass
class Comment:
    at: str                 # ISO 8601, UTC
    author: str = ""        # a login; shown only when the board has people = true
    body: str = ""
    url: str = ""


@dataclass
class Item:
    key: str                # how people name it: "#92" on GitHub, "LAN-12" in a markdown board
    title: str
    state: str              # open | closed
    url: str = ""
    kind: str = ""          # the tracker's type: Task, Bug, Feature, Epic ...
    column: str | None = None
    column_source: str = "" # board (read from the board) | history (the last status change) | status | file | none
    labels: list = field(default_factory=list)
    assignees: list = field(default_factory=list)
    parent: str | None = None
    children: list = field(default_factory=list)
    blocked_by: list = field(default_factory=list)
    blocking: list = field(default_factory=list)
    prs: list = field(default_factory=list)          # PullRequest
    created: str = ""       # ISO 8601, UTC
    updated: str = ""
    closed: str = ""
    close_reason: str = ""  # completed | not_planned | duplicate | "" when open or unknown
    milestone: str = ""
    body: str = ""
    comments: int = 0       # how many there are on the tracker
    thread: list = field(default_factory=list)       # Comment, oldest first: the last COMMENTS_READ when there are more
    history: list = field(default_factory=list)      # [{"at": iso, "from": column, "to": column}]
    fields: dict = field(default_factory=dict)       # any other field the board carries


@dataclass
class Board:
    name: str
    source: str             # github | jira | markdown
    where: str              # owner/repo, a project URL, or a folder
    fetched_at: str
    columns: list = field(default_factory=list)      # in board order, as far as it is known
    items: list = field(default_factory=list)        # Item
    notes: list = field(default_factory=list)        # what could not be read, and why
    prs_read: bool = True   # False when the tracker's pull requests cannot be read (Jira): their rules stand down
    # Cards outside the snapshot's window (closed long ago, or in another project) that a card on the board
    # points to: a blocker, a parent, a sub-item. Read only to say where they stand; never counted as the
    # board's own work.
    outside: list = field(default_factory=list)      # Item

    def lookup(self):
        """Every card the snapshot knows, the board's own and the ones read from outside it."""
        out = {i.key: i for i in self.outside}
        out.update(self.by_key())
        return out

    def by_key(self):
        return {i.key: i for i in self.items}

    def to_json(self):
        return json.dumps(asdict(self), indent=1, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d):
        def item(raw):
            raw = dict(raw)
            raw["prs"] = [PullRequest(**p) for p in raw.get("prs", [])]
            raw["thread"] = [Comment(**c) for c in raw.get("thread", [])]
            return Item(**raw)
        return cls(name=d["name"], source=d["source"], where=d.get("where", ""), fetched_at=d["fetched_at"],
                   columns=list(d.get("columns", [])), items=[item(r) for r in d.get("items", [])],
                   notes=list(d.get("notes", [])), prs_read=d.get("prs_read", True),
                   outside=[item(r) for r in d.get("outside", [])])


OUTSIDE_LIMIT = 500         # at most this many cards are read from outside the snapshot in one read


def outside_keys(items, limit=OUTSIDE_LIMIT):
    """([keys], how many were left out): the cards an OPEN card points to (blocked by, blocking, parent,
    sub-items) that are not among `items`. Blockers first, as they decide whether work can start."""
    have = {i.key for i in items}
    first, rest = [], []
    for it in items:
        if it.state != "open":
            continue
        for k in it.blocked_by:
            if k and k not in have:
                first.append(k)
        for k in list(it.blocking) + [it.parent] + list(it.children):
            if k and k not in have:
                rest.append(k)
    keys = list(dict.fromkeys(first + rest))
    return keys[:limit], max(0, len(keys) - limit)


def outside_notes(read, unread, left):
    """What a snapshot says about the cards read from outside its window."""
    out = []
    if read:
        out.append(f"{read} cards outside this snapshot were read because an open card points to them (a blocker, a "
                   "parent or a sub-item); they are shown where they stand and never counted as the board's work.")
    if unread:
        out.append(f"{len(unread)} cards an open card points to could not be read (gone, moved, or not visible to this "
                   "sign-in): " + ", ".join(unread[:20]) + ("..." if len(unread) > 20 else "") + ". They count as unknown.")
    if left:
        out.append(f"{left} more cards outside the snapshot were not read: one read takes at most {OUTSIDE_LIMIT}.")
    return out

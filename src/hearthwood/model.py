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
class Item:
    key: str                # how people name it: "#92" on GitHub, "LAN-12" in a markdown board
    title: str
    state: str              # open | closed
    url: str = ""
    kind: str = ""          # the tracker's type: Task, Bug, Feature, Epic ...
    column: str | None = None
    column_source: str = "" # board (read from the board) | history (the last status change) | file | none
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
    comments: int = 0
    history: list = field(default_factory=list)      # [{"at": iso, "from": column, "to": column}]
    fields: dict = field(default_factory=dict)       # any other field the board carries


@dataclass
class Board:
    name: str
    source: str             # github | markdown
    where: str              # owner/repo, a project URL, or a folder
    fetched_at: str
    columns: list = field(default_factory=list)      # in board order, as far as it is known
    items: list = field(default_factory=list)        # Item
    notes: list = field(default_factory=list)        # what could not be read, and why

    def by_key(self):
        return {i.key: i for i in self.items}

    def to_json(self):
        return json.dumps(asdict(self), indent=1, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d):
        items = []
        for raw in d.get("items", []):
            raw = dict(raw)
            raw["prs"] = [PullRequest(**p) for p in raw.get("prs", [])]
            items.append(Item(**raw))
        return cls(name=d["name"], source=d["source"], where=d.get("where", ""), fetched_at=d["fetched_at"],
                   columns=list(d.get("columns", [])), items=items, notes=list(d.get("notes", [])))

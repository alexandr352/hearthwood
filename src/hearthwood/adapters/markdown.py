"""A board kept as a folder of markdown files: one ticket per file, a few lines of front matter.

    ---
    key: LAN-12
    title: Show the sync status in the header
    status: In Progress
    type: Task
    labels: [ui, needs:design]
    assignees: [sam]
    parent: LAN-3
    blocked_by: [LAN-10]
    pr: open                    # none | open | draft | merged | closed
    created: 2026-09-01
    updated: 2026-10-01
    closed:                     # a date once it is finished
    close_reason:               # completed | not_planned | duplicate
    ---
    The ticket's text.

An optional `_board.md` in the folder names the columns in order: `columns: [Backlog, Todo, ...]`.
It is the demo board's format, and a way to try hearthwood on a board you write by hand.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from ..model import Board, Item, PullRequest

FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def parse_value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [v.strip().strip("'\"") for v in raw[1:-1].split(",") if v.strip()]
    return raw.strip("'\"")


def parse(text):
    """(front matter dict, body). A file without front matter is all body."""
    m = FRONT.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        line = line.split(" #", 1)[0].rstrip()
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        meta[k.strip().lower()] = parse_value(v)
    return meta, m.group(2)


def _list(v):
    if isinstance(v, list):
        return v
    return [v] if v else []


def _date(v):
    v = (v or "").strip() if isinstance(v, str) else ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return v + "T00:00:00Z"
    return v


def read_board(name, folder, done_columns=("Done",), now=None):
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"no such folder: {folder}")
    now = now or datetime.now(timezone.utc)
    board = Board(name=name, source="markdown", where=str(folder), fetched_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    index = folder / "_board.md"
    if index.exists():
        meta, _ = parse(index.read_text(encoding="utf-8"))
        board.columns = _list(meta.get("columns"))
    for p in sorted(folder.glob("*.md")):
        if p.name.startswith("_"):
            continue
        meta, body = parse(p.read_text(encoding="utf-8"))
        key = meta.get("key") or p.stem
        status = meta.get("status") or None
        closed = _date(meta.get("closed"))
        state = (meta.get("state") or ("closed" if closed or (status in done_columns) else "open")).lower()
        pr = (meta.get("pr") or "none").lower()
        prs = [] if pr in ("", "none") else [PullRequest(number=0, state="open" if pr == "draft" else pr,
                                                         draft=pr == "draft")]
        board.items.append(Item(
            key=key, title=meta.get("title") or p.stem, state=state, url=str(p), kind=meta.get("type") or "",
            column=status, column_source="file" if status else "none",
            labels=_list(meta.get("labels")), assignees=_list(meta.get("assignees")),
            parent=meta.get("parent") or None, blocked_by=_list(meta.get("blocked_by")),
            prs=prs, created=_date(meta.get("created")), updated=_date(meta.get("updated")) or _date(meta.get("created")),
            closed=closed, close_reason=(meta.get("close_reason") or ("completed" if state == "closed" else "")),
            milestone=meta.get("milestone") or "", body=body.strip()))
    keys = {i.key: i for i in board.items}
    for it in board.items:
        if it.parent in keys:
            keys[it.parent].children.append(it.key)
        for b in it.blocked_by:
            if b in keys:
                keys[b].blocking.append(it.key)
    if not board.columns:
        seen = []
        for it in board.items:
            if it.column and it.column not in seen:
                seen.append(it.column)
        board.columns = seen
    return board

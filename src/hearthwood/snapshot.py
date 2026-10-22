"""`manager read`: take a snapshot of a board and keep it in the home.

A snapshot is the board as it stood when it was read. The facts and the reading work on a
snapshot, never on the live tracker, so an analysis can always be read again and argued with.
"""

import re

from . import credentials, home, jira_auth
from .adapters import github, jira, markdown
from .model import Board

# A dependency written in a ticket's text, the way people write them when the tracker has no
# field for it: "Depends on #12", "Blocked by LAN-4, LAN-9", "DEPENDS-ON: #3 #5".
DEP_LINE = re.compile(r"^\W*(depends[\s-]+on|blocked[\s-]+by|requires|waits[\s-]+for)\b[\s:]*(.*)$", re.I)


def text_dependencies(body, keys):
    """Keys named on a dependency line of `body`, or on the lines right after it up to a blank one."""
    found, lines, i = [], (body or "").splitlines(), 0
    while i < len(lines):
        m = DEP_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        chunk = [m.group(2)]
        i += 1
        while i < len(lines) and lines[i].strip() and not DEP_LINE.match(lines[i]):
            chunk.append(lines[i])
            i += 1
        for k in re.findall(r"(?<![\w/])(#\d+|[A-Z][A-Z0-9]+-\d+)\b", " ".join(chunk)):
            if k in keys and k not in found:
                found.append(k)
    return found


def enrich(board):
    """What every adapter's board gets: dependencies written in text, and the links both ways."""
    keys = board.by_key()
    for it in board.items:
        deps = [k for k in text_dependencies(it.body, keys) if k != it.key and k not in it.blocked_by]
        if deps:
            it.fields["depends_in_text"] = deps
    for it in board.items:
        for k in it.fields.get("depends_in_text", []):
            other = keys.get(k)
            if other and it.key not in other.blocking:
                other.blocking.append(it.key)
    return board


def take(b, transport=None, progress=None):
    """Read board `b` (a home.BoardHome) and store the snapshot. Returns (Board, path)."""
    s = b.settings
    if b.source == "github":
        token, where_from = credentials.load_token(b)
        if not token:
            raise ValueError(f"no GitHub token: looked in {where_from}")
        board = github.read_board(b.name, b.where, project=int(s.get("project") or 0),
                                  project_owner=s.get("project_owner") or "", token=token, transport=transport,
                                  closed_days=int(s["rules"].get("closed_days", 60)), progress=progress,
                                  outside_comments=int(s["rules"].get("outside_comments", 5)))
    elif b.source == "jira":
        auth = jira_auth.BoardAuth(b, transport=transport)
        board = jira.read_board(b.name, s["cloud_id"], s["site"], s["project"], auth.header, board_id=int(s.get("board_id") or 0),
                                transport=transport, renew=auth.renew, closed_days=int(s["rules"].get("closed_days", 60)),
                                progress=progress, outside_comments=int(s["rules"].get("outside_comments", 5)))
    elif b.source == "markdown":
        board = markdown.read_board(b.name, b.where, done_columns=tuple(s["columns"].get("done", [])))
    else:
        raise ValueError(f"unknown source {b.source!r} in {b.dir / 'board.toml'}")
    enrich(board)
    b.snapshots.mkdir(parents=True, exist_ok=True)
    path = b.snapshots / f"{home.stamp()}.json"
    path.write_text(board.to_json(), encoding="utf-8")
    return board, path


def load(path):
    import json
    return Board.from_dict(json.loads(path.read_text(encoding="utf-8")))

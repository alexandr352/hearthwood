"""Read a Jira Cloud project, and its board when the grant may, into a Board.

Read-only: every request is a GET, or the search's POST, which reads. Everything goes through
Atlassian's API address for the site (https://api.atlassian.com/ex/jira/<cloud id>), with the
Authorization header the caller supplies: the user's own sign-in in hearthwood itself
(jira_auth.BoardAuth), anything else in a test.

  issues   every open issue of the project (unresolved, and not in a Done status), and the ones
           updated within `closed_days`, in the
           board's rank order: title, type, status, labels, assignee, parent, sub-tasks, "is
           blocked by" links, the resolution, the description, the newest comments and the
           history of status changes.
  board    the board's columns, in order, and which statuses sit in each: an issue's column is
           the column its status belongs to. Without the board (no board, or no permission) the
           column is the status name, and the snapshot says so.
  outside  the issues an open issue points to (blocked by, blocking, parent, sub-tasks) that the
           window above left out, closed long ago or in another project: read by key, so a blocker
           finished long ago reads as finished, not as unknown.

Jira keeps pull requests in its development panel, which has no public API: pull requests are
not read, the snapshot says so, and the rules about pull requests stand down for this board.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ..model import Board, Comment, Item, outside_keys, outside_notes

API = "https://api.atlassian.com/ex/jira/{cloud_id}"
PAGE = 50                   # issues per search page; each carries its history and comments
COMMENTS = 20
FIELDS = ["summary", "status", "issuetype", "labels", "assignee", "parent", "subtasks", "issuelinks", "created",
          "updated", "resolutiondate", "resolution", "description", "comment", "priority", "fixVersions"]
NOT_PLANNED = {"won't do", "won't fix", "wont do", "wont fix", "cannot reproduce", "declined", "rejected",
               "obsolete", "incomplete", "abandoned", "not a bug", "out of scope"}


class JiraError(Exception):
    pass


def urllib_transport(method, url, headers, body=None, timeout=120):
    """(status, headers, body). A network failure or timeout is answered as 599, which is retried."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e.reason):
            raise                              # not a passing failure: retrying cannot help
        return 599, {}, json.dumps({"message": f"no answer: {e.reason}"}).encode()
    except (TimeoutError, OSError) as e:
        return 599, {}, json.dumps({"message": f"no answer: {e}"}).encode()


class Jira:
    def __init__(self, cloud_id, auth, transport=None, sleep=time.sleep, renew=None):
        """`auth()` returns the Authorization header; `renew()`, when given, is tried once after a 401."""
        self.base = API.format(cloud_id=cloud_id)
        self.auth, self.transport, self.sleep, self.renew = auth, transport or urllib_transport, sleep, renew
        self.requests = 0

    def call(self, method, path, params=None, body=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        renewed = False
        for attempt in range(5):
            headers = {"Authorization": self.auth(), "Accept": "application/json", "User-Agent": "hearthwood"}
            if data is not None:
                headers["Content-Type"] = "application/json"
            status, rh, raw = self.transport(method, url, headers, data)
            self.requests += 1
            if status == 401 and b"scope does not match" in (raw or b""):
                raise JiraError(f"the sign-in does not include the permission {path} needs (Atlassian: scope does not match)")
            if status == 401 and self.renew and not renewed:
                renewed = True
                self.renew()
                continue
            if status == 429 or status in (502, 503, 504, 599):
                wait = rh.get("Retry-After") or rh.get("retry-after")
                self.sleep(min(float(wait), 60) if wait and str(wait).replace(".", "").isdigit() else 2 * (attempt + 1))
                continue
            break
        try:
            out = json.loads(raw or b"{}")
        except ValueError:
            out = {}
        if status != 200 and not isinstance(out, dict):
            out = {}
        if status == 401:
            raise JiraError("Jira refused the sign-in (401): sign in again with `manager connect jira --again`")
        if status != 200:
            msgs = out.get("errorMessages") or list((out.get("errors") or {}).values()) or [out.get("message") or ""]
            raise JiraError(f"Jira answered {status} for {path}: {'; '.join(m for m in msgs if m) or 'no reason given'}")
        return out

    def get(self, path, params=None):
        return self.call("GET", path, params)


# --- Jira's document format, as plain text -------------------------------------------------

def adf_to_text(node):
    """Atlassian Document Format (the JSON Jira keeps descriptions and comments in) as readable text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    out = []
    _adf(node, out, "")
    text = "".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def _kids(node, out, prefix):
    for c in node.get("content") or []:
        _adf(c, out, prefix)


def _adf(node, out, prefix):
    t, a = node.get("type"), node.get("attrs") or {}
    if t == "text":
        text = node.get("text", "")
        link = next((m.get("attrs", {}).get("href") for m in node.get("marks") or [] if m.get("type") == "link"), None)
        out.append(f"{text} ({link})" if link and link != text else text)
    elif t == "hardBreak":
        out.append("\n" + prefix)
    elif t in ("paragraph", "heading"):
        if t == "heading":
            out.append("#" * int(a.get("level") or 1) + " ")
        _kids(node, out, prefix)
        out.append("\n\n" + prefix)
    elif t in ("bulletList", "orderedList"):
        for n, item in enumerate(node.get("content") or [], int(a.get("order") or 1)):
            out.append(("- " if t == "bulletList" else f"{n}. "))
            sub = []
            _kids(item, sub, prefix + "  ")
            out.append("".join(sub).strip() + "\n" + prefix)
        out.append("\n" + prefix)
    elif t == "codeBlock":
        out.append("```\n")
        _kids(node, out, "")
        out.append("\n```\n\n" + prefix)
    elif t == "blockquote":
        sub = []
        _kids(node, sub, "")
        out.append("\n".join("> " + line for line in "".join(sub).strip().splitlines()) + "\n\n" + prefix)
    elif t == "rule":
        out.append("---\n\n" + prefix)
    elif t == "mention":
        out.append(a.get("text") or "@someone")
    elif t == "emoji":
        out.append(a.get("text") or a.get("shortName") or "")
    elif t in ("inlineCard", "blockCard", "embedCard"):
        out.append(a.get("url") or "")
    elif t in ("media", "mediaInline"):
        out.append("[attachment]")
    elif t == "status":
        out.append(f"[{a.get('text', '')}]")
    elif t == "date":
        try:
            out.append(datetime.fromtimestamp(int(a.get("timestamp")) / 1000, timezone.utc).strftime("%Y-%m-%d"))
        except (TypeError, ValueError):
            pass
    elif t == "table":
        for row in node.get("content") or []:
            cells = []
            for cell in row.get("content") or []:
                sub = []
                _kids(cell, sub, "")
                cells.append(" ".join("".join(sub).split()))
            out.append("| " + " | ".join(cells) + " |\n" + prefix)
        out.append("\n" + prefix)
    else:
        _kids(node, out, prefix)


# --- mapping -----------------------------------------------------------------------------

def utc(ts):
    """Jira's '2026-10-01T12:34:56.789+0200' as '2026-10-01T10:34:56Z'."""
    if not ts:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(ts, fmt).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return ts


def close_reason(resolution):
    name = ((resolution or {}).get("name") or "").strip().lower()
    if "duplicate" in name:
        return "duplicate"
    if name in NOT_PLANNED:
        return "not_planned"
    return "completed"


def current_sprint(value):
    """The sprint a card is in now: the running one if any, else the last it was put in (a card carried
    over keeps its old sprints in the list)."""
    sprints = [s for s in (value if isinstance(value, list) else [value]) if isinstance(s, dict) and s.get("name")]
    if not sprints:
        return None
    active = [s for s in sprints if (s.get("state") or "").lower() == "active"]
    return (active or sprints)[-1]


def _who(user):
    return (user or {}).get("displayName") or ""


def issue_to_item(n, site_url, column_of, sprint_field=None, rank=None, comments_kept=COMMENTS):
    f = n.get("fields") or {}
    status = f.get("status") or {}
    # Finished: resolved, or in a status of the Done category. Some workflows never put a status in that
    # category and only resolve, so either one counts.
    done = bool(f.get("resolution")) or ((status.get("statusCategory") or {}).get("key") == "done")
    column = column_of(status.get("id"), status.get("name"))
    blocked_by, blocking, duplicates = [], [], []
    for link in f.get("issuelinks") or []:
        kind = ((link.get("type") or {}).get("name") or "").lower()
        if kind == "blocks":
            if link.get("inwardIssue"):
                blocked_by.append(link["inwardIssue"]["key"])
            if link.get("outwardIssue"):
                blocking.append(link["outwardIssue"]["key"])
        elif kind == "duplicate":
            other = link.get("inwardIssue") or link.get("outwardIssue")
            if other:
                duplicates.append(other["key"])
    c = f.get("comment") or {}
    comments = c.get("comments") or []
    thread = [Comment(at=utc(x.get("created")), author=_who(x.get("author")), body=adf_to_text(x.get("body")))
              for x in comments][-comments_kept:] if comments_kept else []
    history = []
    for h in ((n.get("changelog") or {}).get("histories") or []):
        for it in h.get("items") or []:
            if it.get("field") == "status":
                history.append({"at": utc(h.get("created")),
                                "from": column_of(it.get("from"), it.get("fromString"))[0] or it.get("fromString"),
                                "to": column_of(it.get("to"), it.get("toString"))[0] or it.get("toString")})
    history.sort(key=lambda x: x["at"])
    fields = {}
    if rank is not None:
        fields["rank"] = rank
    if (f.get("priority") or {}).get("name"):
        fields["priority"] = f["priority"]["name"]
    if f.get("fixVersions"):
        fields["fix_versions"] = [v.get("name") for v in f["fixVersions"] if v.get("name")]
    if duplicates:
        fields["duplicates"] = duplicates
    s = current_sprint(f.get(sprint_field)) if sprint_field else None
    if s:
        fields.update(sprint=s["name"], sprint_state=(s.get("state") or "").lower(), sprint_start=utc(s.get("startDate")),
                      sprint_end=utc(s.get("endDate")), sprint_goal=(s.get("goal") or "").strip())
    return Item(
        key=n["key"], title=f.get("summary") or "", state="closed" if done else "open",
        url=f"{site_url.rstrip('/')}/browse/{n['key']}", kind=((f.get("issuetype") or {}).get("name") or ""),
        column=column[0], column_source=column[1], labels=list(f.get("labels") or []),
        assignees=[_who(f.get("assignee"))] if _who(f.get("assignee")) else [],
        parent=((f.get("parent") or {}).get("key") or None),
        children=[s["key"] for s in f.get("subtasks") or [] if s.get("key")],
        blocked_by=blocked_by, blocking=blocking, prs=[], created=utc(f.get("created")), updated=utc(f.get("updated")),
        closed=utc(f.get("resolutiondate")) if done else "", close_reason=close_reason(f.get("resolution")) if done else "",
        milestone=", ".join(fields.get("fix_versions", [])), body=adf_to_text(f.get("description")),
        comments=int(c.get("total") or len(comments)), thread=thread, history=history, fields=fields)


# --- reading -----------------------------------------------------------------------------

def find_board(jira, project):
    """The project's boards: [(id, name, type)]."""
    out = jira.get("/rest/agile/1.0/board", {"projectKeyOrId": project, "maxResults": 50})
    return [(b["id"], b.get("name", ""), b.get("type", "")) for b in out.get("values") or []]


def board_columns(jira, board_id):
    """([column names in order], {status id: column name})."""
    cfg = jira.get(f"/rest/agile/1.0/board/{board_id}/configuration")
    names, by_status = [], {}
    for col in (cfg.get("columnConfig") or {}).get("columns") or []:
        names.append(col.get("name"))
        for s in col.get("statuses") or []:
            by_status[str(s.get("id"))] = col.get("name")
    return names, by_status


def sprint_field_id(jira):
    """The id of the sprint field (a custom field, named differently on every site), or None."""
    try:
        found = jira.get("/rest/api/3/field")
    except JiraError:
        return None
    for f in found if isinstance(found, list) else []:
        if ((f.get("schema") or {}).get("custom") or "").endswith(":gh-sprint"):
            return f["id"]
    return None


def search(jira, jql, fields, progress=None):
    token, out = None, []
    while True:
        body = {"jql": jql, "fields": fields, "expand": "changelog", "maxResults": PAGE}
        if token:
            body["nextPageToken"] = token
        page = jira.call("POST", "/rest/api/3/search/jql", body=body)
        out += page.get("issues") or []
        if progress:
            progress(len(out))
        token = page.get("nextPageToken")
        if not token or page.get("isLast", False):
            return out


KEY = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")


def read_outside(jira, keys, site_url, column_of, sprint_field=None, comments_kept=5):
    """([Item], [keys not read]) for issues named by key. One search per page of keys; when Jira refuses a
    page (a key that no longer exists, or one this sign-in may not see, fails the whole search), that page
    is read one issue at a time and the keys that still cannot be read are named."""
    keys = [k for k in dict.fromkeys(keys) if KEY.match(k or "")]
    fields = FIELDS + ([sprint_field] if sprint_field else [])

    def column(status_id, status_name):
        # an issue of another project has a status the board does not show: its status is its column
        col = column_of(status_id, status_name)
        return col if col[0] else ((status_name or None), "status" if status_name else "none")
    found = []
    for i in range(0, len(keys), PAGE):
        chunk = keys[i:i + PAGE]
        try:
            issues = search(jira, "key in (" + ",".join(chunk) + ")", fields)
        except JiraError:
            issues = []
            for k in chunk:
                try:
                    issues.append(jira.get(f"/rest/api/3/issue/{k}", {"fields": ",".join(fields), "expand": "changelog"}))
                except JiraError:
                    continue
        found += [issue_to_item(n, site_url, column, sprint_field, comments_kept=comments_kept) for n in issues]
    got = {it.key for it in found}
    return [it for it in found if it.key in set(keys)], [k for k in keys if k not in got]


def read_board(name, cloud_id, site_url, project, auth, board_id=0, transport=None, renew=None, closed_days=60,
               now=None, progress=None, sleep=time.sleep, outside_comments=5):
    now = now or datetime.now(timezone.utc)
    jira = Jira(cloud_id, auth, transport=transport, renew=renew, sleep=sleep)
    notes = []
    columns, by_status = [], {}
    try:
        if not board_id:
            boards = find_board(jira, project)
            if boards:
                board_id = boards[0][0]
                if len(boards) > 1:
                    notes.append(f"project {project} has {len(boards)} boards; read the first, \"{boards[0][1]}\" "
                                 f"(#{board_id}). `board_id` in board.toml chooses another.")
        if board_id:
            columns, by_status = board_columns(jira, board_id)
    except JiraError as e:
        notes.append(f"the board could not be read ({e}); each item's column is its status instead.")
    if not by_status:
        if not notes:
            notes.append(f"project {project} has no board; each item's column is its status.")

    def column_of(status_id, status_name):
        if by_status:
            col = by_status.get(str(status_id))
            return (col, "board") if col else (None, "none")
        return (status_name or None, "status" if status_name else "none")

    sprint = sprint_field_id(jira)
    fields = FIELDS + ([sprint] if sprint else [])
    window = (f'project = "{project}" AND ((resolution is EMPTY AND statusCategory != Done) '
              f'OR updated >= -{int(closed_days)}d)')
    ranked = True
    try:
        issues = search(jira, window + " ORDER BY Rank ASC", fields, progress)
    except JiraError:
        ranked = False
        issues = search(jira, window + " ORDER BY updated DESC", fields, progress)
        notes.append("the issues have no rank here (no Jira Software board order), so ready work is ordered by number.")
    items = [issue_to_item(n, site_url, column_of, sprint, rank=(i + 1) if ranked else None)
             for i, n in enumerate(issues)]
    keys = {it.key: it for it in items}
    for it in items:
        p = keys.get(it.parent)
        if p and it.key not in p.children:
            p.children.append(it.key)
    if not columns:
        for it in items:
            for c in [it.column] + [h["to"] for h in it.history]:
                if c and c not in columns:
                    columns.append(c)
    cut = sum(1 for it in items if it.comments > len(it.thread))
    wanted, left = outside_keys(items)
    outside, unread = read_outside(jira, wanted, site_url, column_of, sprint, outside_comments) if wanted else ([], [])
    board = Board(name=name, source="jira", where=f"{site_url.rstrip('/')} {project}",
                  fetched_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"), columns=columns, items=items, prs_read=False,
                  outside=outside)
    board.notes = notes + [
        "pull requests are not read: Jira keeps them in its development panel, which has no public API. The rules "
        "about pull requests stand down for this board."]
    board.notes += outside_notes(len(outside), unread, left)
    if cut:
        board.notes.append(f"{cut} items have more comments than the newest {COMMENTS} that were read.")
    board.notes.append(f"Jira requests made: {jira.requests}.")
    return board


"""Read a GitHub repository's issues, and its Projects board when the token may, into a Board.

Read-only. Every request is a GraphQL query; nothing here can write. Two levels of access:

  issues   the token reads the repository's issues: titles, labels, sub-issues, "blocked by"
           links, linked pull requests, the newest comments and the history of status changes.
           Each issue's column is then its LAST status change, and the snapshot says so.
  board    the token also reads the Projects board: the column comes from the board itself,
           and so does the board's order. A fine-grained token needs the owner's permission
           "Projects: read" for this (an organization permission when an organization owns it).
  outside  the issues an open issue points to (blocked by, blocking, parent, sub-issues) that the
           window left out, closed long ago or in another repository: read by number, so a
           blocker finished long ago reads as finished, not as unknown.
"""

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from ..model import Board, Comment, Item, PullRequest, outside_keys, outside_notes

API = "https://api.github.com/graphql"
PAGE = 25
COMMENTS = 20               # the newest comments of each issue; the count says how many there are in all

ISSUE_FIELDS = """
  number title url state stateReason createdAt updatedAt closedAt body
  issueType { name }
  milestone { title }
  comments(last: %d) { totalCount nodes { createdAt url body author { login } } }
  labels(first: 30) { nodes { name } }
  assignees(first: 10) { nodes { login } }
  parent { number repository { nameWithOwner } }
  subIssues(first: 50) { pageInfo { hasNextPage endCursor } nodes { number repository { nameWithOwner } } }
  blockedBy(first: 30) { pageInfo { hasNextPage endCursor } nodes { number repository { nameWithOwner } } }
  blocking(first: 30) { pageInfo { hasNextPage endCursor } nodes { number repository { nameWithOwner } } }
  closedByPullRequestsReferences(first: 10, includeClosedPrs: true) { nodes { number state isDraft merged url } }
  timelineItems(last: 40, itemTypes: [PROJECT_V2_ITEM_STATUS_CHANGED_EVENT]) {
    nodes { ... on ProjectV2ItemStatusChangedEvent { createdAt previousStatus status } }
  }
"""

ISSUES_QUERY = """
query($owner: String!, $repo: String!, $states: [IssueState!], $after: String) {
  repository(owner: $owner, name: $repo) {
    nameWithOwner
    issues(first: %d, after: $after, states: $states, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
  rateLimit { cost remaining resetAt }
}
""" % (PAGE, ISSUE_FIELDS % COMMENTS)

# A list cut by the first page above (a goal with more than 50 sub-items) is read on, 100 at a time,
# so a count never stops silently at the page size.
MORE_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      %s(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { number repository { nameWithOwner } } }
    }
  }
  rateLimit { cost remaining resetAt }
}
"""
LINKS = (("subIssues", "children"), ("blockedBy", "blocked_by"), ("blocking", "blocking"))


def read_more(gh, owner, repo, number, field, after, home_repo):
    """The rest of one issue's list, after the cursor where the first page stopped."""
    out = []
    while after:
        data, errors = gh.query(MORE_QUERY % field, {"owner": owner, "repo": repo, "number": number, "after": after})
        conn = (((data.get("repository") or {}).get("issue") or {}).get(field)) or {}
        if not conn:
            msg = "; ".join(e.get("message", "") for e in errors) or "no answer"
            raise GitHubError(f"cannot read the rest of #{number}'s {field}: {msg}")
        out += [_key(x, home_repo) for x in conn.get("nodes") or [] if x]
        page = conn.get("pageInfo") or {}
        after = page.get("endCursor") if page.get("hasNextPage") else None
    return out


# Issues read by number, OUTSIDE_PAGE to a query, each under its own alias; an issue that is gone or
# hidden answers null with an error of its own, and the others still come back.
OUTSIDE_PAGE = 20
OUTSIDE_KEY = re.compile(r"^(?:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+))?#(\d+)$")


def read_outside(gh, keys, home_repo, comments_kept=5):
    """([Item], [keys not read]) for issues named by key: "#12" in this repository, "owner/repo#12" in another."""
    home_owner, _, home_name = home_repo.partition("/")
    wanted = []
    for k in dict.fromkeys(keys):
        m = OUTSIDE_KEY.match(k or "")
        if m:
            wanted.append((k, m.group(1) or home_owner, m.group(2) or home_name, int(m.group(3))))
    fields = ISSUE_FIELDS % max(1, comments_kept)
    found = []
    for i in range(0, len(wanted), OUTSIDE_PAGE):
        chunk = wanted[i:i + OUTSIDE_PAGE]
        parts = [f'i{n}: repository(owner: {json.dumps(o)}, name: {json.dumps(r)}) {{ issue(number: {num}) {{ {fields} }} }}'
                 for n, (_, o, r, num) in enumerate(chunk)]
        try:
            data, _ = gh.query("query { %s rateLimit { cost remaining resetAt } }" % " ".join(parts), {})
        except GitHubError:
            continue                          # these keys stay unread, and the snapshot names them
        for n, (k, o, r, num) in enumerate(chunk):
            node = ((data.get(f"i{n}") or {}).get("issue"))
            if not node:
                continue
            it = issue_to_item(node, home_repo)
            it.key = k                        # "owner/repo#12" stays itself; issue_to_item names every issue "#12"
            if not comments_kept:
                it.thread = []
            found.append(it)
    got = {it.key for it in found}
    return found, [k for k, *_ in wanted if k not in got] + [k for k in dict.fromkeys(keys) if not OUTSIDE_KEY.match(k or "")]


PROJECT_QUERY = """
query($owner: String!, $number: Int!, $after: String) {
  %s(login: $owner) {
    projectV2(number: $number) {
      title url
      fields(first: 50) { nodes { ... on ProjectV2SingleSelectField { name options { name } } } }
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          content { ... on Issue { number repository { nameWithOwner } } }
          fieldValues(first: 30) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldIterationValue { title field { ... on ProjectV2FieldCommon { name } } }
            }
          }
        }
      }
    }
  }
}
"""


class GitHubError(Exception):
    pass


def urllib_transport(url, headers, body, timeout=60):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class GitHub:
    def __init__(self, token, transport=None, sleep=time.sleep):
        self.token = token
        self.transport = transport or urllib_transport
        self.sleep = sleep
        self.cost = 0

    def query(self, query, variables):
        """(data, errors). Raises only when nothing usable came back."""
        body = json.dumps({"query": query, "variables": variables}).encode()
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                   "User-Agent": "hearthwood", "GraphQL-Features": "sub_issues,issue_types"}
        for attempt in range(3):
            status, raw = self.transport(API, headers, body)
            if status in (502, 503, 504) and attempt < 2:
                self.sleep(2 * (attempt + 1))
                continue
            break
        if status == 401:
            raise GitHubError("GitHub refused the token (401): it is wrong, expired or revoked")
        try:
            out = json.loads(raw or b"{}")
        except ValueError:
            raise GitHubError(f"GitHub answered {status} with something that is not JSON")
        if status != 200 and not out.get("data"):
            raise GitHubError(f"GitHub answered {status}: {out.get('message') or out}")
        rl = (out.get("data") or {}).get("rateLimit") or {}
        self.cost += rl.get("cost") or 0
        return out.get("data") or {}, out.get("errors") or []


def _key(ref, home_repo):
    if not ref:
        return None
    repo = (ref.get("repository") or {}).get("nameWithOwner") or home_repo
    return f"#{ref['number']}" if repo.lower() == home_repo.lower() else f"{repo}#{ref['number']}"


def _iso(ts):
    return ts or ""


def _history(timeline):
    out = []
    for n in (timeline or {}).get("nodes") or []:
        if n and "status" in n:
            out.append({"at": n.get("createdAt") or "", "from": n.get("previousStatus") or None,
                        "to": n.get("status") or None})
    return sorted(out, key=lambda h: h["at"])


def _thread(comments):
    out = []
    for c in (comments or {}).get("nodes") or []:
        if c:
            out.append(Comment(at=c.get("createdAt") or "", author=((c.get("author") or {}).get("login") or ""),
                               body=c.get("body") or "", url=c.get("url") or ""))
    return sorted(out, key=lambda c: c.at)


def issue_to_item(n, home_repo):
    prs = []
    for p in (n.get("closedByPullRequestsReferences") or {}).get("nodes") or []:
        if not p:
            continue
        state = "merged" if p.get("merged") else (p.get("state") or "").lower()
        prs.append(PullRequest(number=p["number"], state=state, draft=bool(p.get("isDraft")), url=p.get("url") or ""))
    history = _history(n.get("timelineItems"))
    column = history[-1]["to"] if history else None
    reason = (n.get("stateReason") or "").lower()
    return Item(
        key=f"#{n['number']}", title=n.get("title") or "", state=(n.get("state") or "").lower(),
        url=n.get("url") or "", kind=((n.get("issueType") or {}).get("name") or ""),
        column=column, column_source="history" if column else "none",
        labels=[x["name"] for x in (n.get("labels") or {}).get("nodes") or [] if x],
        assignees=[x["login"] for x in (n.get("assignees") or {}).get("nodes") or [] if x],
        parent=_key(n.get("parent"), home_repo),
        children=[_key(x, home_repo) for x in (n.get("subIssues") or {}).get("nodes") or [] if x],
        blocked_by=[_key(x, home_repo) for x in (n.get("blockedBy") or {}).get("nodes") or [] if x],
        blocking=[_key(x, home_repo) for x in (n.get("blocking") or {}).get("nodes") or [] if x],
        prs=prs, created=_iso(n.get("createdAt")), updated=_iso(n.get("updatedAt")),
        closed=_iso(n.get("closedAt")), close_reason=reason if n.get("state") == "CLOSED" else "",
        milestone=((n.get("milestone") or {}).get("title") or ""), body=n.get("body") or "",
        comments=((n.get("comments") or {}).get("totalCount") or 0), thread=_thread(n.get("comments")),
        history=history)


def read_issues(gh, owner, repo, closed_days, now=None, progress=None):
    """Every open issue, and the closed ones updated within `closed_days`."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=closed_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items, home_repo = [], f"{owner}/{repo}"
    for states in (["OPEN"], ["CLOSED"]):
        after = None
        while True:
            data, errors = gh.query(ISSUES_QUERY, {"owner": owner, "repo": repo, "states": states, "after": after})
            r = data.get("repository")
            if r is None:
                msg = "; ".join(e.get("message", "") for e in errors) or "no repository in the answer"
                raise GitHubError(f"cannot read {owner}/{repo}: {msg}")
            home_repo = r.get("nameWithOwner") or home_repo
            conn = r["issues"]
            stop = False
            for n in conn.get("nodes") or []:
                if not n:
                    continue
                if states == ["CLOSED"] and (n.get("updatedAt") or "") < cutoff:
                    stop = True
                    break
                item = issue_to_item(n, home_repo)
                for field, attr in LINKS:
                    page = (n.get(field) or {}).get("pageInfo") or {}
                    if page.get("hasNextPage"):
                        getattr(item, attr).extend(read_more(gh, owner, repo, n["number"], field, page.get("endCursor"),
                                                             home_repo))
                items.append(item)
            if progress:
                progress(len(items))
            if stop or not conn["pageInfo"]["hasNextPage"]:
                break
            after = conn["pageInfo"]["endCursor"]
    return items, home_repo


def read_project(gh, owner, number, home_repo, status_field="Status"):
    """{issue key: (column, rank, other fields)}, the board's column order, and a note when unread."""
    last_errors = []
    for kind in ("organization", "user"):
        after, rows, columns, rank = None, {}, [], 0
        while True:
            data, errors = gh.query(PROJECT_QUERY % kind, {"owner": owner, "number": number, "after": after})
            project = ((data.get(kind) or {}).get("projectV2"))
            if project is None:
                last_errors = errors
                break
            if not columns:
                for f in (project.get("fields") or {}).get("nodes") or []:
                    if f and f.get("name") == status_field:
                        columns = [o["name"] for o in f.get("options") or []]
            conn = project["items"]
            for node in conn.get("nodes") or []:
                content = (node or {}).get("content") or {}
                if "number" not in content:
                    continue
                key = _key(content, home_repo)
                fields, column = {}, None
                for v in (node.get("fieldValues") or {}).get("nodes") or []:
                    if not v or not v.get("field"):
                        continue
                    name = v["field"].get("name")
                    value = next((v[k] for k in ("name", "text", "number", "date", "title") if k in v), None)
                    if name == status_field:
                        column = value
                    elif name and name not in ("Title", "Assignees", "Labels", "Linked pull requests",
                                                "Milestone", "Repository", "Reviewers", "Parent issue",
                                                "Sub-issues progress"):
                        fields[name] = value
                rank += 1
                rows[key] = (column, rank, fields)
            if not conn["pageInfo"]["hasNextPage"]:
                return rows, columns, None
            after = conn["pageInfo"]["endCursor"]
    why = "; ".join(sorted({e.get("message", "") for e in last_errors})) or "the project was not found"
    if "personal access token" in why or "FORBIDDEN" in json.dumps(last_errors):
        why += (" (a fine-grained token needs the permission \"Projects: read\" from the project's owner; "
                "for an organization that is an organization permission)")
    return None, [], why


def read_board(name, where, project=0, project_owner="", token=None, transport=None, closed_days=60,
               now=None, progress=None, outside_comments=5):
    owner, _, repo = where.partition("/")
    if not owner or not repo:
        raise GitHubError(f"`where` must be owner/repo, not {where!r}")
    gh = GitHub(token, transport=transport)
    now = now or datetime.now(timezone.utc)
    items, home_repo = read_issues(gh, owner, repo, closed_days, now=now, progress=progress)
    wanted, left = outside_keys(items)
    outside, unread = read_outside(gh, wanted, home_repo, outside_comments) if wanted else ([], [])
    board = Board(name=name, source="github", where=home_repo, fetched_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  items=items, outside=outside)
    if project:
        rows, columns, why = read_project(gh, project_owner or owner, int(project), home_repo)
        if rows is None:
            board.notes.append(f"the Projects board #{project} could not be read: {why}. Each column is the "
                               "issue's last status change instead.")
        else:
            board.columns = columns
            for it in items:
                if it.key in rows:
                    it.column, rank, fields = rows[it.key]
                    it.column_source = "board"
                    it.fields = dict(fields, rank=rank)
                else:
                    it.column, it.column_source = None, "none"
            for it in outside:                # off the board, an outside card keeps its last status change
                if it.key in rows:
                    it.column, rank, fields = rows[it.key]
                    it.column_source = "board"
                    it.fields = dict(fields)
            missing = sum(1 for it in items if it.column_source == "none" and it.state == "open")
            if missing:
                board.notes.append(f"{missing} open issues are not on the Projects board #{project}.")
    if not board.columns:
        seen = []
        for it in items:
            for h in it.history:
                for c in (h["from"], h["to"]):
                    if c and c not in seen:
                        seen.append(c)
        board.columns = seen
        board.notes.append("columns are taken from the issues' status history, so their order is a guess "
                           "and an issue whose status never changed has no column.")
    board.notes += outside_notes(len(outside), unread, left)
    board.notes.append(f"GitHub rate limit spent: {gh.cost} points.")
    return board

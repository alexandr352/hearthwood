"""Read a GitHub repository's issues, and its Projects board when the token may, into a Board.

Read-only. Every request is a GraphQL query; nothing here can write. Two levels of access:

  issues   the token reads the repository's issues: titles, labels, sub-issues, "blocked by"
           links, linked pull requests and the history of status changes. Each issue's column
           is then its LAST status change, and the snapshot says so.
  board    the token also reads the Projects board: the column comes from the board itself,
           and so does the board's order. A fine-grained token needs the owner's permission
           "Projects: read" for this (an organization permission when an organization owns it).
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from ..model import Board, Item, PullRequest

API = "https://api.github.com/graphql"
PAGE = 25

ISSUE_FIELDS = """
  number title url state stateReason createdAt updatedAt closedAt body
  issueType { name }
  milestone { title }
  comments { totalCount }
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
""" % (PAGE, ISSUE_FIELDS)

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
        comments=((n.get("comments") or {}).get("totalCount") or 0), history=history)


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
               now=None, progress=None):
    owner, _, repo = where.partition("/")
    if not owner or not repo:
        raise GitHubError(f"`where` must be owner/repo, not {where!r}")
    gh = GitHub(token, transport=transport)
    now = now or datetime.now(timezone.utc)
    items, home_repo = read_issues(gh, owner, repo, closed_days, now=now, progress=progress)
    board = Board(name=name, source="github", where=home_repo, fetched_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  items=items)
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
    board.notes.append(f"GitHub rate limit spent: {gh.cost} points.")
    return board

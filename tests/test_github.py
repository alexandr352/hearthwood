import json
import re
import unittest

import helpers  # noqa: F401

from hearthwood.adapters import github


def issue(n, state="OPEN", updated="2026-10-09T00:00:00Z", statuses=(), **kw):
    node = {"number": n, "title": kw.get("title", f"Issue {n}"), "url": f"https://github.com/o/r/issues/{n}",
            "state": state, "stateReason": kw.get("reason"), "createdAt": "2026-09-01T00:00:00Z", "updatedAt": updated,
            "closedAt": kw.get("closed"), "body": kw.get("body", ""), "issueType": {"name": "Task"}, "milestone": None,
            "comments": {"totalCount": 2}, "labels": {"nodes": [{"name": l} for l in kw.get("labels", [])]},
            "assignees": {"nodes": [{"login": a} for a in kw.get("assignees", [])]},
            "parent": {"number": kw["parent"], "repository": {"nameWithOwner": "o/r"}} if kw.get("parent") else None,
            "subIssues": {"nodes": []},
            "blockedBy": {"nodes": [{"number": b, "repository": {"nameWithOwner": "o/r"}} for b in kw.get("blocked_by", [])]},
            "blocking": {"nodes": []},
            "closedByPullRequestsReferences": {"nodes": kw.get("prs", [])},
            "timelineItems": {"nodes": [{"createdAt": f"2026-09-0{i + 1}T00:00:00Z", "previousStatus": a, "status": b}
                                        for i, (a, b) in enumerate(statuses)]}}
    return node


class FakeGitHub:
    def __init__(self, open_pages, closed_pages, project=None, status=200):
        self.open, self.closed, self.project, self.status, self.queries = open_pages, closed_pages, project, status, []
        self.more, self.outside = {}, {}

    def __call__(self, url, headers, body):
        assert headers["Authorization"] == "Bearer T"
        q = json.loads(body)
        self.queries.append(q)
        if self.status != 200:
            return self.status, b'{"message": "Bad credentials"}'
        v = q["variables"]
        asked = re.findall(r'(i\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\) \{ issue\(number: (\d+)\)', q["query"])
        if asked:                             # the outside read: issues by number, one alias each
            data = {a: {"issue": self.outside.get((o, r, int(n)))} for a, o, r, n in asked}
            errors = [{"message": f"Could not resolve to an Issue with the number of {n}."}
                      for a, o, r, n in asked if not data[a]["issue"]]
            return 200, json.dumps({"data": data, "errors": errors}).encode()
        if "issue(number:" in q["query"]:
            field = next(f for f in ("subIssues", "blockedBy", "blocking") if f + "(first: 100" in q["query"])
            rest = self.more[(v["number"], field)]
            i = int(v["after"])
            page = rest[i - 1] if i - 1 < len(rest) else []
            conn = {"pageInfo": {"hasNextPage": i < len(rest), "endCursor": str(i + 1)},
                    "nodes": [{"number": c, "repository": {"nameWithOwner": "o/r"}} for c in page]}
            return 200, json.dumps({"data": {"repository": {"issue": {field: conn}}}}).encode()
        if "projectV2" in q["query"]:
            kind = "organization" if "organization(" in q["query"] else "user"
            if self.project is None or kind != "organization":
                return 200, json.dumps({"data": {kind: None}, "errors": [
                    {"type": "FORBIDDEN", "message": "Resource not accessible by personal access token"}]}).encode()
            return 200, json.dumps({"data": {"organization": {"projectV2": self.project}}}).encode()
        pages = self.open if v["states"] == ["OPEN"] else self.closed
        i = int(v["after"] or 0)
        conn = {"pageInfo": {"hasNextPage": i + 1 < len(pages), "endCursor": str(i + 1)}, "nodes": pages[i] if pages else []}
        return 200, json.dumps({"data": {"repository": {"nameWithOwner": "o/r", "issues": conn},
                                         "rateLimit": {"cost": 1, "remaining": 4999}}}).encode()


class Read(unittest.TestCase):
    def test_a_goal_with_more_than_one_page_of_sub_items_is_read_whole(self):
        goal = issue(1)
        goal["subIssues"] = {"pageInfo": {"hasNextPage": True, "endCursor": "1"},
                             "nodes": [{"number": c, "repository": {"nameWithOwner": "o/r"}} for c in range(100, 150)]}
        fake = FakeGitHub([[goal]], [[]])
        fake.more[(1, "subIssues")] = [list(range(150, 250)), list(range(250, 264))]
        b = github.read_board("t", "o/r", token="T", transport=fake, closed_days=60)
        kids = b.by_key()["#1"].children
        self.assertEqual(len(kids), 164)
        self.assertEqual((kids[0], kids[-1]), ("#100", "#263"))

    def test_issues_only_takes_columns_from_history(self):
        fake = FakeGitHub([[issue(1, statuses=[("", "Todo"), ("Todo", "In Progress")]), issue(2, blocked_by=[1])],
                           [issue(3)]],
                          [[issue(4, state="CLOSED", reason="COMPLETED", closed="2026-10-01T00:00:00Z"),
                            issue(5, state="CLOSED", updated="2026-01-01T00:00:00Z")]])
        b = github.read_board("t", "o/r", token="T", transport=fake, closed_days=60)
        keys = b.by_key()
        self.assertEqual(sorted(keys), ["#1", "#2", "#3", "#4"])        # #5 is older than the window
        self.assertEqual((keys["#1"].column, keys["#1"].column_source), ("In Progress", "history"))
        self.assertEqual(keys["#2"].blocked_by, ["#1"])
        self.assertEqual(keys["#4"].close_reason, "completed")
        self.assertTrue(any("status history" in n for n in b.notes))

    def test_the_board_gives_columns_and_order(self):
        project = {"title": "P", "url": "u",
                   "fields": {"nodes": [{"name": "Status", "options": [{"name": "Todo"}, {"name": "Done"}]}]},
                   "items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [
                       {"content": {"number": 2, "repository": {"nameWithOwner": "o/r"}},
                        "fieldValues": {"nodes": [{"name": "Todo", "field": {"name": "Status"}},
                                                  {"name": "P1", "field": {"name": "Priority"}}]}},
                       {"content": {"number": 1, "repository": {"nameWithOwner": "o/r"}},
                        "fieldValues": {"nodes": [{"name": "Done", "field": {"name": "Status"}}]}}]}}
        fake = FakeGitHub([[issue(1, statuses=[("", "Todo")]), issue(2), issue(3)]], [[]], project=project)
        b = github.read_board("t", "o/r", project=7, token="T", transport=fake)
        k = b.by_key()
        self.assertEqual(b.columns, ["Todo", "Done"])
        self.assertEqual((k["#1"].column, k["#1"].column_source), ("Done", "board"))
        self.assertEqual(k["#2"].fields, {"Priority": "P1", "rank": 1})
        self.assertEqual(k["#3"].column_source, "none")
        self.assertTrue(any("not on the Projects board" in n for n in b.notes))

    def test_an_unreadable_board_is_said_and_why(self):
        fake = FakeGitHub([[issue(1, statuses=[("", "Todo")])]], [[]], project=None)
        b = github.read_board("t", "o/r", project=7, token="T", transport=fake)
        self.assertTrue(any("Projects: read" in n for n in b.notes))
        self.assertEqual(b.by_key()["#1"].column_source, "history")

    def test_a_refused_token_is_said_plainly(self):
        with self.assertRaises(github.GitHubError) as e:
            github.read_board("t", "o/r", token="T", transport=FakeGitHub([[]], [[]], status=401))
        self.assertIn("refused the token", str(e.exception))

    def test_pull_requests(self):
        prs = [{"number": 9, "state": "MERGED", "isDraft": False, "merged": True, "url": "u"},
               {"number": 10, "state": "OPEN", "isDraft": True, "merged": False, "url": "u"}]
        fake = FakeGitHub([[issue(1, prs=prs)]], [[]])
        it = github.read_board("t", "o/r", token="T", transport=fake).by_key()["#1"]
        self.assertEqual([(p.number, p.state, p.draft) for p in it.prs], [(9, "merged", False), (10, "open", True)])


if __name__ == "__main__":
    unittest.main()

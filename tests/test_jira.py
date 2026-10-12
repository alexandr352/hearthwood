import contextlib
import io
import json
import os
import threading
import time
import unittest
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from helpers import TempHome, settings

from hearthwood import cli, facts, home, jira_auth, snapshot
from hearthwood.adapters import jira
from hearthwood.model import Board

CLOUD = "cloud-1"
SITE = "https://acme.atlassian.net"


def adf(*paragraphs):
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}]}
                                                    for p in paragraphs]}


def issue(key, status=("10001", "To Do", "new"), **kw):
    f = {"summary": kw.get("title", f"Issue {key}"),
         "status": {"id": status[0], "name": status[1], "statusCategory": {"key": status[2]}},
         "issuetype": {"name": kw.get("type", "Task")}, "labels": kw.get("labels", []),
         "assignee": {"displayName": kw["assignee"]} if kw.get("assignee") else None,
         "parent": {"key": kw["parent"]} if kw.get("parent") else None,
         "subtasks": [{"key": k} for k in kw.get("subtasks", [])],
         "issuelinks": kw.get("links", []), "created": "2026-09-01T10:00:00.000+0200",
         "updated": kw.get("updated", "2026-10-09T12:00:00.000+0000"),
         "resolutiondate": kw.get("resolved"), "resolution": {"name": kw["resolution"]} if kw.get("resolution") else None,
         "description": kw.get("description"), "priority": {"name": "Medium"}, "fixVersions": [],
         "comment": {"comments": kw.get("comments", []), "total": kw.get("total", len(kw.get("comments", [])))}}
    if kw.get("sprint"):
        f["customfield_10020"] = [{"name": kw["sprint"]}]
    return {"key": key, "fields": f, "changelog": {"histories": kw.get("histories", [])}}


def blocked_by(key):
    return {"type": {"name": "Blocks"}, "inwardIssue": {"key": key}}


CONFIG = {"columnConfig": {"columns": [
    {"name": "To Do", "statuses": [{"id": "10001"}]},
    {"name": "In Progress", "statuses": [{"id": "3"}]},
    {"name": "In Review", "statuses": [{"id": "10010"}]},
    {"name": "Done", "statuses": [{"id": "10002"}]}]}}


class FakeAtlassian:
    """Answers like Atlassian's API, from canned pages; records every request."""

    def __init__(self, pages, boards=((7, "APP board", "kanban"),), config=CONFIG, board_status=200, rank=True):
        self.pages, self.boards, self.config, self.board_status, self.rank = pages, boards, config, board_status, rank
        self.calls, self.fail_401 = [], 0

    def __call__(self, method, url, headers, body=None):
        u = urllib.parse.urlparse(url)
        self.calls.append((method, u.path, headers.get("Authorization"), json.loads(body) if body else None))
        assert u.netloc == "api.atlassian.com" and u.path.startswith(f"/ex/jira/{CLOUD}/"), url
        path = u.path[len(f"/ex/jira/{CLOUD}"):]
        if self.fail_401:
            self.fail_401 -= 1
            return 401, {}, b'{"code":401,"message":"Unauthorized"}'
        if path == "/rest/agile/1.0/board":
            if self.board_status != 200:
                return self.board_status, {}, b'{"code":401,"message":"Unauthorized; scope does not match"}'
            return 200, {}, json.dumps({"values": [{"id": i, "name": n, "type": t} for i, n, t in self.boards]}).encode()
        if path.endswith("/configuration"):
            return 200, {}, json.dumps(self.config).encode()
        if path == "/rest/api/3/field":
            return 200, {}, json.dumps([{"id": "customfield_10020", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
                                        {"id": "summary", "schema": {}}]).encode()
        if path == "/rest/api/3/search/jql":
            q = json.loads(body)
            if "ORDER BY Rank" in q["jql"] and not self.rank:
                return 400, {}, b'{"errorMessages":["Field \'Rank\' does not exist"]}'
            i = int(q.get("nextPageToken") or 0)
            page = {"issues": self.pages[i]}
            if i + 1 < len(self.pages):
                page["nextPageToken"] = str(i + 1)
            return 200, {}, json.dumps(page).encode()
        if path == "/rest/api/3/project/search":
            return 200, {}, json.dumps({"values": [{"key": "APP", "name": "The app"}]}).encode()
        return 404, {}, b"{}"


def read(fake, **kw):
    return jira.read_board("app", CLOUD, SITE, "APP", lambda: "Bearer T", transport=fake, sleep=lambda s: None,
                           now=datetime(2026, 10, 12, tzinfo=timezone.utc), **kw)


class Adf(unittest.TestCase):
    def test_paragraphs_lists_and_links(self):
        doc = {"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Goal"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "See "},
                                              {"type": "text", "text": "the spec", "marks": [{"type": "link", "attrs": {"href": "https://x.test/s"}}]},
                                              {"type": "hardBreak"}, {"type": "mention", "attrs": {"text": "@Kim Lee"}},
                                              {"type": "text", "text": " agrees."}]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "two"}]}]}]},
            {"type": "codeBlock", "content": [{"type": "text", "text": "x = 1"}]},
            {"type": "table", "content": [{"type": "tableRow", "content": [
                {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}]},
                {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]}]}]},
            {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "m1"}}]}]}
        text = jira.adf_to_text(doc)
        self.assertIn("## Goal", text)
        self.assertIn("See the spec (https://x.test/s)\n@Kim Lee agrees.", text)
        self.assertIn("- one\n- two", text)
        self.assertIn("```\nx = 1\n```", text)
        self.assertIn("| a | b |", text)
        self.assertIn("[attachment]", text)
        self.assertNotIn("\n\n\n", text)

    def test_nothing_and_plain_text(self):
        self.assertEqual(jira.adf_to_text(None), "")
        self.assertEqual(jira.adf_to_text("plain"), "plain")


class Read(unittest.TestCase):
    def test_columns_come_from_the_board_and_the_order_from_rank(self):
        fake = FakeAtlassian([[issue("APP-3"), issue("APP-1", status=("3", "In Progress", "indeterminate"))]])
        b = read(fake)
        self.assertEqual(b.columns, ["To Do", "In Progress", "In Review", "Done"])
        k = b.by_key()
        self.assertEqual((k["APP-1"].column, k["APP-1"].column_source), ("In Progress", "board"))
        self.assertEqual((k["APP-3"].fields["rank"], k["APP-1"].fields["rank"]), (1, 2))
        search = next(c for c in fake.calls if c[1].endswith("/search/jql"))
        self.assertIn('project = "APP" AND ((resolution is EMPTY AND statusCategory != Done) OR updated >= -60d) '
                      'ORDER BY Rank ASC', search[3]["jql"])
        self.assertEqual(search[3]["expand"], "changelog")
        self.assertIn("customfield_10020", search[3]["fields"])
        self.assertTrue(all(c[2] == "Bearer T" for c in fake.calls))
        self.assertTrue(all(c[0] == "GET" or c[1].endswith("/search/jql") for c in fake.calls))   # reads only
        self.assertFalse(b.prs_read)
        self.assertTrue(any("pull requests are not read" in n for n in b.notes))

    def test_the_mapping(self):
        done = ("10002", "Done", "done")
        b = read(FakeAtlassian([[
            issue("APP-1", type="Epic", title="The epic"),
            issue("APP-2", parent="APP-1", links=[blocked_by("APP-3")], labels=["ui"], assignee="Kim Lee",
                  description=adf("What to build."), sprint="Sprint 4", subtasks=["APP-5"],
                  comments=[{"created": "2026-10-02T09:00:00.000+0200", "author": {"displayName": "Kim Lee"},
                             "body": adf("Waiting on APP-3.")}], total=31,
                  histories=[{"created": "2026-10-01T08:00:00.000+0000",
                              "items": [{"field": "status", "from": "10001", "fromString": "To Do", "to": "3", "toString": "In Progress"}]}]),
            issue("APP-3", status=done, resolution="Done", resolved="2026-10-05T10:00:00.000+0000"),
            issue("APP-4", status=done, resolution="Won't Do", resolved="2026-10-05T10:00:00.000+0000"),
            issue("APP-6", status=done, resolution="Duplicate", resolved="2026-10-05T10:00:00.000+0000"),
        ]]))
        k = b.by_key()
        two = k["APP-2"]
        self.assertEqual((two.parent, two.blocked_by, two.labels, two.assignees), ("APP-1", ["APP-3"], ["ui"], ["Kim Lee"]))
        self.assertEqual(two.children, ["APP-5"])
        self.assertIn("APP-2", k["APP-1"].children)
        self.assertEqual(two.url, "https://acme.atlassian.net/browse/APP-2")
        self.assertEqual(two.body, "What to build.")
        self.assertEqual(two.created, "2026-09-01T08:00:00Z")                     # +0200 made UTC
        self.assertEqual((two.comments, len(two.thread)), (31, 1))
        self.assertEqual((two.thread[0].author, two.thread[0].at, two.thread[0].body),
                         ("Kim Lee", "2026-10-02T07:00:00Z", "Waiting on APP-3."))
        self.assertEqual(two.history, [{"at": "2026-10-01T08:00:00Z", "from": "To Do", "to": "In Progress"}])
        self.assertEqual(two.fields["sprint"], "Sprint 4")
        self.assertEqual(k["APP-1"].kind, "Epic")
        self.assertEqual([(k[x].state, k[x].close_reason) for x in ("APP-3", "APP-4", "APP-6")],
                         [("closed", "completed"), ("closed", "not_planned"), ("closed", "duplicate")])
        self.assertEqual(k["APP-3"].closed, "2026-10-05T10:00:00Z")
        self.assertTrue(any("more comments than the newest 20" in n for n in b.notes))

    def test_resolved_counts_as_finished_even_outside_the_done_category(self):
        it = read(FakeAtlassian([[issue("APP-1", status=("5", "Closed", "indeterminate"), resolution="Fixed",
                                        resolved="2026-10-05T10:00:00.000+0000")]])).by_key()["APP-1"]
        self.assertEqual((it.state, it.close_reason, it.closed), ("closed", "completed", "2026-10-05T10:00:00Z"))

    def test_only_the_newest_twenty_comments_are_kept(self):
        many = [{"created": f"2026-10-01T{h:02d}:00:00.000+0000", "author": {"displayName": "A"}, "body": adf(str(h))}
                for h in range(24)]
        it = read(FakeAtlassian([[issue("APP-1", comments=many)]])).by_key()["APP-1"]
        self.assertEqual((it.comments, len(it.thread), it.thread[0].body, it.thread[-1].body), (24, 20, "4", "23"))

    def test_pages_are_followed(self):
        b = read(FakeAtlassian([[issue("APP-1")], [issue("APP-2")], [issue("APP-3")]]))
        self.assertEqual(sorted(b.by_key()), ["APP-1", "APP-2", "APP-3"])

    def test_without_the_board_the_status_is_the_column(self):
        fake = FakeAtlassian([[issue("APP-1", status=("3", "In Progress", "indeterminate"))]], board_status=401)
        b = read(fake)
        it = b.by_key()["APP-1"]
        self.assertEqual((it.column, it.column_source), ("In Progress", "status"))
        self.assertTrue(any("scope does not match" in n for n in b.notes))
        self.assertEqual(b.columns, ["In Progress"])

    def test_no_rank_falls_back_to_updated_and_says_so(self):
        b = read(FakeAtlassian([[issue("APP-1")]], rank=False))
        self.assertNotIn("rank", b.by_key()["APP-1"].fields)
        self.assertTrue(any("no rank" in n for n in b.notes))

    def test_a_401_renews_once(self):
        fake = FakeAtlassian([[issue("APP-1")]])
        fake.fail_401 = 1
        renewed = []
        b = read(fake, renew=lambda: renewed.append(1))
        self.assertEqual(renewed, [1])
        self.assertEqual(len(b.items), 1)

    def test_a_missing_permission_is_named_not_renewed(self):
        client = jira.Jira(CLOUD, lambda: "Bearer T", transport=FakeAtlassian([[]], board_status=401),
                           renew=lambda: self.fail("must not renew"))
        with self.assertRaises(jira.JiraError) as e:
            jira.find_board(client, "APP")
        self.assertIn("scope does not match", str(e.exception))

    def test_a_rate_limit_waits_as_told(self):
        answers = [(429, {"Retry-After": "3"}, b"{}"), (200, {}, b'{"values": []}')]
        waited = []
        client = jira.Jira(CLOUD, lambda: "Bearer T", transport=lambda *a: answers.pop(0), sleep=waited.append)
        self.assertEqual(jira.find_board(client, "APP"), [])
        self.assertEqual(waited, [3.0])

    def test_pull_request_rules_stand_down(self):
        b = read(FakeAtlassian([[issue("APP-1", status=("10010", "In Review", "indeterminate"))]]))
        a = facts.Analysis(b, settings()).run()
        self.assertFalse([f for f in a.findings if f.rule in ("review-without-pr", "merged-not-done", "pr-not-in-review")])

    def test_a_snapshot_keeps_that_prs_were_not_read(self):
        b = read(FakeAtlassian([[issue("APP-1")]]))
        self.assertFalse(Board.from_dict(json.loads(b.to_json())).prs_read)


class Token:
    """Atlassian's token endpoint and accessible-resources, faked."""

    def __init__(self):
        self.posts, self.n = [], 0
        self.refuse = False

    def __call__(self, method, url, headers, body=None):
        if url == jira_auth.RESOURCES_URL:
            return 200, {}, json.dumps([{"id": CLOUD, "url": SITE, "name": "acme", "scopes": list(jira_auth.SCOPES)}]).encode()
        assert url == jira_auth.TOKEN_URL
        f = json.loads(body)
        self.posts.append(f)
        if self.refuse:
            return 403, {}, b'{"error":"unauthorized_client","error_description":"refresh_token is invalid"}'
        self.n += 1
        return 200, {}, json.dumps({"access_token": f"A{self.n}", "refresh_token": f"R{self.n}", "expires_in": 3600,
                                    "scope": " ".join(jira_auth.SCOPES)}).encode()


class Auth(unittest.TestCase):
    def test_the_link_asks_for_read_scopes_with_state_and_pkce(self):
        verifier, challenge = jira_auth.new_pkce()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(jira_auth.authorize_url("CID", "S1", challenge)).query)
        self.assertEqual((q["client_id"], q["state"], q["response_type"], q["prompt"]), (["CID"], ["S1"], ["code"], ["consent"]))
        self.assertEqual(q["redirect_uri"], ["http://localhost:8768/callback"])
        self.assertEqual((q["code_challenge"], q["code_challenge_method"]), ([challenge], ["S256"]))
        scopes = q["scope"][0].split()
        self.assertIn("offline_access", scopes)
        self.assertFalse([s for s in scopes if s.startswith("write") or s.startswith("manage")])

    def test_a_pasted_address_must_answer_this_sign_in(self):
        self.assertEqual(jira_auth.code_from("http://localhost:8768/callback?code=C1&state=S1", "S1"), "C1")
        for bad in ("http://localhost:8768/callback?code=C1&state=OTHER", "http://localhost:8768/callback?state=S1",
                    "http://localhost:8768/callback?error=access_denied&state=S1"):
            with self.assertRaises(jira_auth.JiraAuthError):
                jira_auth.code_from(bad, "S1")

    def test_the_browser_redirect_is_caught_once(self):
        got = {}
        t = threading.Thread(target=lambda: got.update(code=jira_auth.wait_for_code("S1", port=18768, timeout=10)))
        t.start()
        for _ in range(50):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18768/callback?code=C9&state=S1", timeout=2) as r:
                    page = r.read().decode()
                break
            except OSError:
                time.sleep(0.1)
        t.join(5)
        self.assertEqual(got["code"], "C9")
        self.assertIn("connected", page)

    def test_the_exchange_sends_the_secret_and_the_verifier(self):
        tok = Token()
        g = jira_auth.exchange({"client_id": "CID", "client_secret": "SEC"}, "C1", "V1", transport=tok, now=1000)
        self.assertEqual((tok.posts[0]["grant_type"], tok.posts[0]["code_verifier"], tok.posts[0]["client_secret"]),
                         ("authorization_code", "V1", "SEC"))
        self.assertEqual((g["access_token"], g["refresh_token"], g["expires_at"]), ("A1", "R1", 4600))

    def board_with_grant(self, t, grant):
        jira_auth.save_app(t.h, "CID", "SEC")
        b = home.add_board("app", "jira", f"{SITE} APP", h=t.h,
                           extra=f'site = "{SITE}"\ncloud_id = "{CLOUD}"\nproject = "APP"\nboard_id = 7\n')
        jira_auth.save_grant(b, grant)
        return b

    def test_files_are_private(self):
        with TempHome() as t:
            b = self.board_with_grant(t, {"access_token": "A", "refresh_token": "R", "expires_at": 0})
            for p in (jira_auth.app_path(t.h), jira_auth.grant_path(b)):
                self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)

    def test_an_expired_token_is_renewed_and_the_new_refresh_token_kept(self):
        with TempHome() as t:
            b = self.board_with_grant(t, {"access_token": "A0", "refresh_token": "R0", "expires_at": 100})
            tok = Token()
            auth = jira_auth.BoardAuth(b, transport=tok, clock=lambda: 1000)
            self.assertEqual(auth.header(), "Bearer A1")
            self.assertEqual(tok.posts[0]["refresh_token"], "R0")
            saved = json.loads(jira_auth.grant_path(b).read_text())
            self.assertEqual((saved["access_token"], saved["refresh_token"]), ("A1", "R1"))
            self.assertEqual(auth.header(), "Bearer A1")                  # still fresh: no second renewal
            self.assertEqual(len(tok.posts), 1)

    def test_a_revoked_grant_asks_for_a_new_sign_in(self):
        with TempHome() as t:
            b = self.board_with_grant(t, {"access_token": "A0", "refresh_token": "R0", "expires_at": 100})
            tok = Token()
            tok.refuse = True
            with self.assertRaises(jira_auth.JiraAuthError) as e:
                jira_auth.BoardAuth(b, transport=tok, clock=lambda: 1000).header()
            self.assertIn("--again", str(e.exception))

    def test_a_snapshot_through_the_board_sign_in(self):
        with TempHome() as t:
            b = self.board_with_grant(t, {"access_token": "A0", "refresh_token": "R0", "expires_at": 10 ** 10})
            fake = FakeAtlassian([[issue("APP-1", comments=[{"created": "2026-10-02T09:00:00.000+0000",
                                                              "author": {"displayName": "Kim Lee"}, "body": adf("ok")}])]])
            board, path = snapshot.take(b, transport=fake)
            self.assertEqual(board.source, "jira")
            self.assertTrue(path.exists())
            self.assertTrue(all(c[2] == "Bearer A0" for c in fake.calls))
            self.assertEqual(board.by_key()["APP-1"].column, "To Do")


def manager(*argv, stdin=""):
    import sys
    buf, old = io.StringIO(), sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(buf):
            code = cli.main(list(argv))
    finally:
        sys.stdin = old
    return code, buf.getvalue()


class Connect(unittest.TestCase):
    def test_connect_by_pasting_the_address(self):
        with TempHome() as t:
            self.assertEqual(manager("connect", "jira-app", "--client-id", "CID", "--secret-stdin", stdin="SEC\n")[0], 0)
            tok, api = Token(), FakeAtlassian([[]])
            old = (jira_auth.urllib_transport, jira.urllib_transport, jira_auth.new_state)
            jira_auth.urllib_transport, jira.urllib_transport = tok, api
            jira_auth.new_state = lambda: "S1"
            try:
                code, text = manager("connect", "jira", "--board", "app", "--paste",
                                     stdin="http://localhost:8768/callback?code=C1&state=S1\n")
            finally:
                jira_auth.urllib_transport, jira.urllib_transport, jira_auth.new_state = old
            self.assertEqual(code, 0, text)
            self.assertIn("https://auth.atlassian.com/authorize?", text)
            self.assertNotIn("SEC", text)
            b = home.BoardHome("app", t.h)
            self.assertEqual((b.source, b.settings["cloud_id"], b.settings["project"], b.settings["board_id"]),
                             ("jira", CLOUD, "APP", 7))
            g = json.loads(jira_auth.grant_path(b).read_text())
            self.assertEqual((g["access_token"], g["refresh_token"], g["site_url"]), ("A1", "R1", SITE))
            self.assertNotEqual(manager("connect", "jira", "--board", "app", "--paste")[0], 0)   # exists: needs --again

    def test_without_an_app_it_says_how_to_add_one(self):
        with TempHome():
            code, _ = manager("connect", "jira", "--board", "app", "--paste")
            self.assertNotEqual(code, 0)

    def test_next_step_for_a_board_that_lost_its_sign_in(self):
        with TempHome() as t:
            home.add_board("app", "jira", f"{SITE} APP", h=t.h, extra=f'site = "{SITE}"\ncloud_id = "{CLOUD}"\nproject = "APP"\n')
            from hearthwood import guide
            cmd, why = guide.next_step(t.h)
            self.assertEqual(cmd, "manager connect jira --board app --again")


if __name__ == "__main__":
    unittest.main()

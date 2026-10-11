import contextlib
import http.client
import io
import json
import threading
import unittest

from helpers import DEMO, TempHome

from hearthwood import cli, home, server


def manager(*argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(list(argv))


class Served(unittest.TestCase):
    def setUp(self):
        self.t = TempHome().__enter__()
        self.addCleanup(self.t.__exit__)
        manager("connect", "markdown", str(DEMO), "--board", "demo")
        manager("analyze", "--read", "--facts-only")
        server.Handler.h = self.t.h
        server.Handler.cfg = home.config(self.t.h)
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read().decode()

    def cookie(self):
        return {"Cookie": f"hw={server.KEY}"}

    def api(self):
        return {"X-HW-Key": server.KEY, "Content-Type": "application/json"}

    # --- the guards -----------------------------------------------------------------

    def test_the_link_sets_the_key_as_a_strict_cookie(self):
        self.assertEqual(self.call("GET", "/?k=wrong")[0], 403)
        status, headers, _ = self.call("GET", f"/?k={server.KEY}")
        self.assertEqual(status, 303)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])

    def test_the_page_needs_the_cookie_and_this_host(self):
        self.assertEqual(self.call("GET", "/")[0], 403)
        self.assertEqual(self.call("GET", "/", headers=self.cookie(), host="evil.example:80")[0], 403)
        status, headers, page = self.call("GET", "/", headers=self.cookie())
        self.assertEqual(status, 200)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("<body class=ui>", page)
        self.assertIn("<aside id=chat", page)
        self.assertIn(f'var KEY="{server.KEY}"', page)
        self.assertNotIn(server.worklog.CHAT, page)
        self.assertIn("data-ask=next>do it with the spirit", page)

    def test_the_api_needs_the_key_in_a_header(self):
        self.assertEqual(self.call("GET", "/api/history", headers=self.cookie())[0], 403)
        self.assertEqual(self.call("POST", "/api/chat", body="{}", headers=self.cookie())[0], 403)
        status, _, body = self.call("GET", "/api/history", headers=self.api())
        self.assertEqual((status, json.loads(body)), (200, []))

    def test_an_oversized_message_is_refused(self):
        big = json.dumps({"message": "x" * (server.MAX_BODY + 1)})
        self.assertEqual(self.call("POST", "/api/chat", body=big, headers=self.api())[0], 413)

    def test_one_message_at_a_time(self):
        server.CHAT_LOCK.acquire()
        try:
            status, _, _ = self.call("POST", "/api/chat", body=json.dumps({"message": "hi"}), headers=self.api())
        finally:
            server.CHAT_LOCK.release()
        self.assertEqual(status, 409)

    # --- the chat ----------------------------------------------------------------

    def test_the_spirit_answers_in_a_stream_and_is_remembered(self):
        status, _, body = self.call("POST", "/api/chat", body=json.dumps({"message": "What first?"}), headers=self.api())
        self.assertEqual(status, 200)
        events = [json.loads(line) for line in body.splitlines() if line]
        self.assertEqual([e["type"] for e in events], ["tool", "text", "text", "text", "done"])
        self.assertEqual(events[0]["text"], "$ manager next")
        self.assertEqual("".join(e["text"] for e in events if e["type"] == "text"), "Look at LAN-3 first: it gates LAN-4.")
        kinds = [m["kind"] for m in json.loads(self.call("GET", "/api/history", headers=self.api())[2])]
        self.assertEqual(kinds, ["me", "tool", "spirit", "meta"])
        runs = home.read_jsonl(self.t.h / "runs.jsonl")
        self.assertEqual(runs[-1]["label"], "spirit (ui)")
        self.assertEqual(runs[-1]["cost_usd"], 0.1)
        call = self.t.calls()[-1]
        self.assertTrue(call["cwd"].endswith("/spirit"))
        self.assertIn('"mode": "spirit"', call["policy"])
        self.call("POST", "/api/chat", body=json.dumps({"message": "And then?"}), headers=self.api())
        self.assertIsNotNone(self.t.calls()[-1]["resume"])

    def test_what_the_person_points_at_reaches_the_spirit(self):
        about = {"ask": "card", "board": "demo", "key": "LAN-3"}
        self.call("POST", "/api/chat", body=json.dumps({"message": "Tell me", "about": about}), headers=self.api())
        self.assertTrue(self.t.calls()[-1]["prompt"].startswith("[The person is looking at card LAN-3 of board demo."))

    def test_tool_lines_show_paths_inside_the_home_relative_to_it(self):
        h = self.t.h
        self.assertEqual(server.describe_tool("Read", {"file_path": f"{h}/boards/demo/criteria.md"}, h),
                         "read boards/demo/criteria.md")
        self.assertEqual(server.describe_tool("Bash", {"command": "manager next"}, h), "$ manager next")
        self.assertEqual(server.describe_tool("Glob", {"pattern": str(h)}, h), "glob .")

    def test_new_forgets_the_conversation(self):
        self.call("POST", "/api/chat", body=json.dumps({"message": "hi"}), headers=self.api())
        self.call("POST", "/api/new", body="{}", headers=self.api())
        self.assertEqual(json.loads(self.call("GET", "/api/history", headers=self.api())[2]), [])
        self.call("POST", "/api/chat", body=json.dumps({"message": "again"}), headers=self.api())
        self.assertIsNone(self.t.calls()[-1]["resume"])

    def test_the_stamp_moves_when_the_board_is_read_again(self):
        before = json.loads(self.call("GET", "/api/stamp", headers=self.api())[2])["stamp"]
        import time
        time.sleep(0.05)
        manager("analyze", "--facts-only")
        after = json.loads(self.call("GET", "/api/stamp", headers=self.api())[2])["stamp"]
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from helpers import DEMO, TempHome

from hearthwood import criteria, facts, home, reading, snapshot

KEYS = {"#1", "#2"}
FIDS = {"stale-abc123"}


def good(**kw):
    a = {"summary": "Fine.", "attention": [{"title": "t", "keys": ["#1"], "finding_ids": ["stale-abc123"], "why": "w",
                                            "next_step": "n", "confidence": "high"}],
         "questions": [{"question": "q?", "for": "you", "keys": []}],
         "proposals": [{"action": "link", "keys": ["#1", "#2"], "change": "c", "why": "w"}]}
    a.update(kw)
    return a


class Contract(unittest.TestCase):
    def test_good(self):
        self.assertEqual(reading.check(good(), KEYS, FIDS), [])

    def test_keys_must_be_on_the_board(self):
        a = good()
        a["attention"][0]["keys"] = ["#9"]
        self.assertTrue(any("not on this board" in d for d in reading.check(a, KEYS, FIDS)))

    def test_finding_ids_must_exist(self):
        a = good()
        a["attention"][0]["finding_ids"] = ["made-up"]
        self.assertTrue(reading.check(a, KEYS, FIDS))

    def test_shape(self):
        self.assertTrue(any("attention" in d for d in reading.check({"summary": "x", "attention": "x"}, KEYS, FIDS)))
        self.assertTrue(reading.check(good(extra=1), KEYS, FIDS))
        self.assertTrue(reading.check(good(attention=[{}] * 11), KEYS, FIDS))
        self.assertTrue(reading.check(good(questions=[{"question": "q", "for": "the boss"}]), KEYS, FIDS))
        self.assertTrue(reading.check(good(proposals=[{"action": "delete", "keys": ["#1"], "change": "c", "why": "w"}]), KEYS, FIDS))
        self.assertEqual(reading.check("text", KEYS, FIDS), ["the answer is not one JSON object"])

    def test_people_stay_out_unless_turned_on(self):
        a = good()
        a["attention"][0]["why"] = "@sam is slow"
        self.assertTrue(any("names people" in d for d in reading.check(a, KEYS, FIDS, logins={"sam"})))
        self.assertEqual(reading.check(a, KEYS, FIDS, logins={"sam"}, people=True), [])
        a["attention"][0]["why"] = "same as before"     # a login inside another word is not a name
        self.assertEqual(reading.check(a, KEYS, FIDS, logins={"sam"}), [])


def demo(t):
    b = home.add_board("demo", "markdown", str(DEMO), h=t.h)
    board, _ = snapshot.take(b)
    a = facts.Analysis(board, b.settings).run()
    d = reading.prepare(b, board, a, {})
    return b, board, a, d


class Run(unittest.TestCase):
    def test_a_good_reading(self):
        with TempHome() as t:
            b, board, a, d = demo(t)
            r, records, status = reading.run(b, d, board, a)
            self.assertIsNotNone(r, status)
            self.assertEqual(json.loads((d / "proposals.json").read_text())[0]["id"], "P1")
            call = t.calls()[0]
            self.assertEqual(json.loads(call["policy"])["mode"], "analyst")
            self.assertIn("--tools", call["argv"])
            self.assertEqual(call["argv"][call["argv"].index("--tools") + 1], "Read,Grep,Glob")
            self.assertTrue(call["prompt"].startswith("READING"))
            self.assertEqual(len(home.read_jsonl(t.h / "runs.jsonl")), 1)

    def test_a_broken_answer_goes_back_to_the_same_session(self):
        with TempHome() as t:
            b, board, a, d = demo(t)
            t.flag("bad-once")
            r, records, status = reading.run(b, d, board, a)
            self.assertIsNotNone(r)
            calls = t.calls()
            self.assertEqual(len(calls), 2)
            self.assertIsNotNone(calls[1]["resume"])
            self.assertTrue(calls[1]["prompt"].startswith("DEVIATION"))
            self.assertIn("2 tries", status)

    def test_three_broken_answers_leave_the_facts_alone(self):
        with TempHome() as t:
            b, board, a, d = demo(t)
            t.flag("always-bad")
            r, records, status = reading.run(b, d, board, a)
            self.assertIsNone(r)
            self.assertEqual(len(t.calls()), 3)
            self.assertTrue((d / "reading-broken.json").exists())
            self.assertIn("broke its contract 3 times", status)

    def test_an_unknown_key_is_returned_as_a_deviation(self):
        with TempHome() as t:
            b, board, a, d = demo(t)
            t.flag("unknown-key")
            r, _, _ = reading.run(b, d, board, a)
            self.assertIsNotNone(r)
            self.assertIn("not on this board", t.calls()[1]["prompt"])

    def test_a_failed_call_is_reported(self):
        with TempHome() as t:
            b, board, a, d = demo(t)
            t.flag("fail")
            r, _, status = reading.run(b, d, board, a)
            self.assertIsNone(r)
            self.assertIn("did not run", status)

    def test_the_reading_sees_criteria_and_earlier_verdicts(self):
        with TempHome() as t:
            b, board, a, d = demo(t)
            fid = next(f.id for f in a.findings if f.rule == "stale")
            criteria.record(t.h, b, d, fid, "disagree", why="search is parked on purpose")
            criteria.add_rule(t.h, "Search work may wait; offline mode comes first.")
            d2 = reading.prepare(b, board, a, criteria.latest_by_target(t.h, b.name))
            prompt = reading.mission(d2)
            self.assertIn("offline mode comes first", prompt)
            self.assertIn("search is parked on purpose", prompt)


if __name__ == "__main__":
    unittest.main()

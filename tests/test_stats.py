import unittest

from helpers import board, item, settings

from hearthwood import stats

NOW = "2026-10-10T00:00:00Z"


def closed(key, when, reason="completed", **kw):
    return item(key, state="closed", column="Done", close_reason=reason, closed=when, **kw)


def run(*items, **st):
    s = settings()
    s["stats"] = {"type_labels": st.get("type_labels", []), "goal_labels": st.get("goal_labels", [])}
    return stats.Stats(board(*items), s).to_dict()


class Headline(unittest.TestCase):
    def test_open_waiting_and_in_flight(self):
        h = run(item("#1"), item("#2", column="Backlog"), item("#3", column="In Progress"), item("#4", column="In Review"),
                closed("#5", "2026-10-01T00:00:00Z"))["headline"]
        self.assertEqual((h["open"], h["waiting"], h["active"], h["review"]), (4, 2, 1, 1))
        self.assertEqual(h["waiting_by_column"], {"Todo": 1, "Backlog": 1})

    def test_created_and_closed_in_the_last_14_days(self):
        h = run(item("#1", created="2026-10-05T00:00:00Z"), item("#2", created="2026-09-01T00:00:00Z"),
                closed("#3", "2026-10-02T00:00:00Z", created="2026-10-01T00:00:00Z"),
                closed("#4", "2026-10-03T00:00:00Z", reason="not_planned"),
                closed("#5", "2026-09-01T00:00:00Z"))["headline"]
        self.assertEqual((h["created_14"], h["closed_14"], h["done_14"], h["dropped_14"]), (2, 2, 1, 1))

    def test_under_no_goal_leaves_goals_out(self):
        h = run(item("#1", children=["#2"]), item("#2", parent="#1"), item("#3"),
                item("#4", labels=["op:objective"]), goal_labels=["op:objective"])["headline"]
        self.assertEqual(h["no_goal"], 1)


class Weeks(unittest.TestCase):
    def test_six_windows_ending_at_the_read(self):
        w = run(item("#1", created="2026-10-09T00:00:00Z"), item("#2", created="2026-10-02T12:00:00Z"),
                closed("#3", "2026-10-08T00:00:00Z"), closed("#4", "2026-10-08T00:00:00Z", reason="not_planned"))["weeks"]
        self.assertEqual(len(w), 6)
        self.assertEqual((w[-1]["created"], w[-1]["done"], w[-1]["dropped"], w[-1]["net"]), (1, 1, 1, -1))
        self.assertEqual(w[-2]["created"], 1)
        self.assertFalse(any(x["short"] for x in w))

    def test_weeks_older_than_closed_days_are_marked_short(self):
        s = settings(closed_days=20)
        s["stats"] = {"type_labels": [], "goal_labels": []}
        w = stats.Stats(board(item("#1")), s).to_dict()["weeks"]
        self.assertEqual([x["short"] for x in w], [True, True, True, True, False, False])


class Goals(unittest.TestCase):
    def test_size_progress_and_growth(self):
        st = run(item("#1", children=["#2", "#3", "#4", "#9"], title="Offline"),
                 item("#2", parent="#1", created="2026-10-05T00:00:00Z"),
                 closed("#3", "2026-10-01T00:00:00Z", parent="#1"), closed("#4", "2026-08-01T00:00:00Z", parent="#1"),
                 item("#5", labels=["op:objective"]), goal_labels=["op:objective"])
        g = st["goals"][0]
        self.assertEqual((g["cards"], g["open"], g["done"], g["progress"], g["unknown"]), (4, 1, 2, 67, 1))
        self.assertEqual((g["added_30"], g["closed_30"], g["added_7"]), (1, 1, 1))
        self.assertEqual(st["empty_goals"], ["#5"])

    def test_a_goal_closed_long_ago_is_not_listed(self):
        st = run(closed("#1", "2026-07-01T00:00:00Z", children=["#2"]), closed("#2", "2026-07-01T00:00:00Z", parent="#1"))
        self.assertEqual(st["goals"], [])


class Types(unittest.TestCase):
    def test_type_from_a_label_pattern_else_the_tracker_type(self):
        st = run(item("#1", labels=["op:bug", "ui"]), item("#2", labels=["op:bug"], column="Backlog"),
                 item("#3", kind="Task"), item("#4", column=None), type_labels=["op:*"])
        types = {t: (counts, total) for t, counts, total in st["types"]}
        self.assertEqual(types["op:bug"][1], 2)
        self.assertEqual(types["Task"][1], 1)
        self.assertIn("(no column)", st["type_columns"])

    def test_ages_and_old_parked_cards(self):
        st = run(item("#1", created="2026-10-08T00:00:00Z"), item("#2", created="2026-09-20T00:00:00Z"),
                 item("#3", created="2026-08-01T00:00:00Z", column="Backlog"),
                 item("#4", created="2026-06-01T00:00:00Z", column="Backlog"))
        self.assertEqual([n for _, n in st["ages"]], [1, 1, 1, 1])
        self.assertEqual((st["parked_old"], st["parked"]), (2, 2))


class Days(unittest.TestCase):
    def test_fourteen_days_by_day(self):
        d = run(item("#1", created="2026-10-09T10:00:00Z"), closed("#2", "2026-10-09T11:00:00Z"))["days"]
        self.assertEqual(len(d), 14)
        last = d[-2]
        self.assertEqual((last["created"], last["done"]), (1, 1))


if __name__ == "__main__":
    unittest.main()

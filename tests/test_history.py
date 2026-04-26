import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src import history as history_mod


class RecordTest(unittest.TestCase):
    def test_first_record_creates_series(self):
        h: dict = {}
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=date(2026, 4, 26))
        self.assertEqual(
            h["大阪|2026-06-02|2026-06-08"],
            [{"date": "2026-04-26", "price": 5791}],
        )

    def test_same_day_overwrites(self):
        h: dict = {}
        today = date(2026, 4, 26)
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 6500, today=today)
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=today)
        series = h["大阪|2026-06-02|2026-06-08"]
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["price"], 5791)

    def test_different_days_append(self):
        h: dict = {}
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 6500, today=date(2026, 4, 22))
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=date(2026, 4, 26))
        series = h["大阪|2026-06-02|2026-06-08"]
        self.assertEqual(len(series), 2)
        self.assertEqual([s["price"] for s in series], [6500, 5791])


class PruneTest(unittest.TestCase):
    def test_drops_old_samples(self):
        today = date(2026, 4, 26)
        h = {
            "大阪|2026-06-02|2026-06-08": [
                {"date": "2026-04-01", "price": 7000},   # 25 days ago — drop
                {"date": "2026-04-15", "price": 6500},   # 11 days ago — keep
                {"date": "2026-04-26", "price": 5791},   # today — keep
            ],
        }
        removed = history_mod.prune(h, today=today)
        self.assertEqual(removed, 1)
        self.assertEqual(len(h["大阪|2026-06-02|2026-06-08"]), 2)

    def test_drops_past_departure_entries(self):
        today = date(2026, 4, 26)
        h = {
            "大阪|2026-04-10|2026-04-15": [{"date": "2026-04-01", "price": 5000}],
            "大阪|2026-06-02|2026-06-08": [{"date": "2026-04-25", "price": 5791}],
        }
        history_mod.prune(h, today=today)
        self.assertNotIn("大阪|2026-04-10|2026-04-15", h)
        self.assertIn("大阪|2026-06-02|2026-06-08", h)


class TrendTest(unittest.TestCase):
    def test_insufficient_samples_returns_none(self):
        h: dict = {}
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=date(2026, 4, 26))
        self.assertIsNone(
            history_mod.trend(h, "大阪", "2026-06-02", "2026-06-08", today=date(2026, 4, 26))
        )

    def test_falling_price(self):
        today = date(2026, 4, 26)
        h: dict = {}
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 7000, today=today - timedelta(days=6))
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 6500, today=today - timedelta(days=3))
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=today)
        t = history_mod.trend(h, "大阪", "2026-06-02", "2026-06-08", today=today)
        self.assertIsNotNone(t)
        self.assertEqual(t["arrow"], "↓")
        self.assertLess(t["change_pct"], 0)
        self.assertEqual(len(t["samples"]), 3)

    def test_rising_price(self):
        today = date(2026, 4, 26)
        h: dict = {}
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5000, today=today - timedelta(days=5))
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5500, today=today - timedelta(days=2))
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=today)
        t = history_mod.trend(h, "大阪", "2026-06-02", "2026-06-08", today=today)
        self.assertEqual(t["arrow"], "↑")
        self.assertGreater(t["change_pct"], 0)

    def test_flat_price(self):
        today = date(2026, 4, 26)
        h: dict = {}
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=today - timedelta(days=3))
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=today)
        t = history_mod.trend(h, "大阪", "2026-06-02", "2026-06-08", today=today)
        self.assertEqual(t["arrow"], "──")

    def test_window_excludes_old_samples(self):
        today = date(2026, 4, 26)
        h: dict = {}
        # 10 days ago is outside the 7-day window
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 7000, today=today - timedelta(days=10))
        history_mod.record(h, "大阪", "2026-06-02", "2026-06-08", 5791, today=today)
        t = history_mod.trend(h, "大阪", "2026-06-02", "2026-06-08", today=today, window_days=7)
        self.assertIsNone(t)  # only 1 sample inside window


class SparklineTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(history_mod._sparkline([]), "")

    def test_single_value_renders(self):
        # All-equal values should render as some valid sparkline char
        s = history_mod._sparkline([5000, 5000, 5000])
        self.assertEqual(len(s), 3)

    def test_descending_renders(self):
        s = history_mod._sparkline([7000, 6500, 5791])
        self.assertEqual(len(s), 3)
        # First char should be highest, last should be lowest
        chars = history_mod._SPARK_CHARS
        self.assertGreater(chars.index(s[0]), chars.index(s[-1]))


class RoundtripTest(unittest.TestCase):
    def test_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            h = {"大阪|2026-06-02|2026-06-08": [{"date": "2026-04-26", "price": 5791}]}
            history_mod.save_history(h, path=path)
            loaded = history_mod.load_history(path=path)
            self.assertEqual(h, loaded)

    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(history_mod.load_history(path=Path(tmp) / "x.json"), {})


if __name__ == "__main__":
    unittest.main()

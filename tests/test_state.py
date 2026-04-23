import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src import state as state_mod


class ShouldNotifyTest(unittest.TestCase):
    def test_never_seen_returns_true(self):
        state: dict = {}
        self.assertTrue(
            state_mod.should_notify(state, "大阪", "2026-06-01", "2026-06-07", 14000)
        )

    def test_same_price_returns_false(self):
        state: dict = {}
        state_mod.record(state, "大阪", "2026-06-01", "2026-06-07", 14000)
        self.assertFalse(
            state_mod.should_notify(state, "大阪", "2026-06-01", "2026-06-07", 14000)
        )

    def test_small_drop_under_threshold_returns_false(self):
        state: dict = {}
        state_mod.record(state, "大阪", "2026-06-01", "2026-06-07", 14000)
        # drop ~1% — below the 5% threshold
        self.assertFalse(
            state_mod.should_notify(state, "大阪", "2026-06-01", "2026-06-07", 13860)
        )

    def test_big_drop_over_threshold_returns_true(self):
        state: dict = {}
        state_mod.record(state, "大阪", "2026-06-01", "2026-06-07", 14000)
        # drop 10% — above the 5% threshold
        self.assertTrue(
            state_mod.should_notify(state, "大阪", "2026-06-01", "2026-06-07", 12600)
        )

    def test_different_watch_name_independent(self):
        state: dict = {}
        state_mod.record(state, "大阪", "2026-06-01", "2026-06-07", 14000)
        # same dates, different watch -> should notify
        self.assertTrue(
            state_mod.should_notify(state, "東京", "2026-06-01", "2026-06-07", 14000)
        )

    def test_custom_threshold(self):
        state: dict = {}
        state_mod.record(state, "大阪", "2026-06-01", "2026-06-07", 10000)
        # 1% drop, threshold set to 0 -> notify
        self.assertTrue(
            state_mod.should_notify(
                state, "大阪", "2026-06-01", "2026-06-07", 9900, drop_threshold=0.0
            )
        )


class PrunePastTest(unittest.TestCase):
    def test_removes_past_entries(self):
        today = date(2026, 6, 1)
        state = {
            "大阪|2026-05-01|2026-05-07": {"price": 1, "notified_at": "2026-04-01"},
            "大阪|2026-07-01|2026-07-07": {"price": 2, "notified_at": "2026-04-01"},
        }
        removed = state_mod.prune_past(state, today=today)
        self.assertEqual(removed, 1)
        self.assertNotIn("大阪|2026-05-01|2026-05-07", state)
        self.assertIn("大阪|2026-07-01|2026-07-07", state)

    def test_today_entry_kept(self):
        today = date(2026, 6, 1)
        state = {"大阪|2026-06-01|2026-06-07": {"price": 1, "notified_at": "2026-04-01"}}
        state_mod.prune_past(state, today=today)
        self.assertIn("大阪|2026-06-01|2026-06-07", state)

    def test_malformed_keys_ignored(self):
        state = {"not|a|valid|date": {"price": 1, "notified_at": "2026-04-01"}}
        state_mod.prune_past(state, today=date.today())
        # Malformed key left intact rather than crashing
        self.assertIn("not|a|valid|date", state)


class RoundtripTest(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = {"大阪|2026-06-01|2026-06-07": {"price": 14000, "notified_at": "2026-04-23"}}
            state_mod.save_state(state, path=path)
            loaded = state_mod.load_state(path=path)
            self.assertEqual(state, loaded)

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nope.json"
            self.assertEqual(state_mod.load_state(path=path), {})

    def test_load_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(state_mod.load_state(path=path), {})

    def test_utf8_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = {"大阪|2026-06-01|2026-06-07": {"price": 14000, "notified_at": "2026-04-23"}}
            state_mod.save_state(state, path=path)
            raw = path.read_text(encoding="utf-8")
            # ensure Chinese characters saved literally (ensure_ascii=False)
            self.assertIn("大阪", raw)


if __name__ == "__main__":
    unittest.main()

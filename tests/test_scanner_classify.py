"""Cover the classify/format split that decides what each scan notifies.

Specifically: a hit that's already in state and didn't drop ≥ DROP_THRESHOLD
must land in `unchanged_hits` (so the body's 📊 持平 section can reconcile
the header's "🟢 有特價" count) — not silently fall off as it did before.
"""

import unittest

from src.config import Watch
from src.scanner import (
    _classify,
    _format_changes,
    _format_unchanged_section,
)
from src.state import _key
from src.travelpayouts_client import FlightQuote


def _watch(name="東京", origin="TPE", dest="HND", adults=2, currency="TWD"):
    return Watch(
        name=name,
        origin=origin,
        destination=dest,
        depart_window_days=120,
        stay_days=[3, 4, 5],
        adults=adults,
        cabin="economy",
        currency=currency,
        max_price=20000,
        date_step_days=1,
    )


def _quote(price=14000, depart="2026-06-01", ret="2026-06-05", adults=2):
    return FlightQuote(
        origin="TPE",
        destination="HND",
        depart_date=depart,
        return_date=ret,
        price=price,
        price_per_person=price / adults,
        currency="TWD",
        airlines=["CI"],
        transfers=0,
    )


class ClassifyTests(unittest.TestCase):
    def test_unchanged_hit_in_state_with_no_drop_lands_in_unchanged(self):
        """The exact bug the user reported: header counted 東京 as 有特價 but
        body had no 東京 because the hit was in state and hadn't dropped 5%."""
        watch = _watch()
        q = _quote(price=14000)
        state = {_key(watch.name, q.depart_date, q.return_date): {"price": 14000}}

        new, drop, gone, unchanged = _classify(state, [(watch, [q])])

        self.assertEqual(new, [])
        self.assertEqual(drop, [])
        self.assertEqual(gone, [])
        self.assertEqual(len(unchanged), 1)
        self.assertEqual(unchanged[0][0].name, "東京")

    def test_significant_drop_goes_to_drop_not_unchanged(self):
        watch = _watch()
        q = _quote(price=10000)  # 10000 vs prev 14000 = ~28% drop
        state = {_key(watch.name, q.depart_date, q.return_date): {"price": 14000}}

        new, drop, gone, unchanged = _classify(state, [(watch, [q])])

        self.assertEqual(len(drop), 1)
        self.assertEqual(unchanged, [])

    def test_first_time_hit_goes_to_new_not_unchanged(self):
        watch = _watch()
        q = _quote(price=14000)

        new, drop, gone, unchanged = _classify({}, [(watch, [q])])

        self.assertEqual(len(new), 1)
        self.assertEqual(unchanged, [])


class UnchangedSectionTests(unittest.TestCase):
    def test_groups_by_watch_and_shows_cheapest_with_count(self):
        watch = _watch(name="東京")
        q1 = _quote(price=14000, depart="2026-06-01", ret="2026-06-05")
        q2 = _quote(price=15000, depart="2026-06-08", ret="2026-06-12")

        out = _format_unchanged_section([(watch, q1), (watch, q2)])

        # Cheapest per-person was 14000/2 = 7000
        self.assertIn("東京", out)
        self.assertIn("7,000/人", out)
        self.assertIn("共 2 筆", out)

    def test_single_hit_omits_count_suffix(self):
        watch = _watch(name="沖繩")
        q = _quote(price=14000)

        out = _format_unchanged_section([(watch, q)])

        self.assertIn("沖繩", out)
        self.assertNotIn("共 1 筆", out)


class FormatChangesIntegrationTests(unittest.TestCase):
    def test_unchanged_section_appears_when_only_unchanged(self):
        """When new+drop+gone are empty but unchanged exists, the body still
        gets a 📊 section. (Caller decides whether to actually send — this
        function just composes; run() gates on has_changes.)"""
        watch = _watch(name="東京")
        q = _quote(price=14000)

        parts = _format_changes(
            new_hits=[],
            drop_hits=[],
            gone=[],
            unchanged_hits=[(watch, q)],
            history={},
            marker="",
        )

        self.assertEqual(len(parts), 1)
        self.assertIn("📊", parts[0])
        self.assertIn("持平", parts[0])


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date

from monitor import VixClose, build_message, detect_crossings


def row(day: int, close: float) -> VixClose:
    return VixClose(date(2026, 1, day), close)


class CrossingTests(unittest.TestCase):
    def test_two_day_confirmation(self):
        result = detect_crossings([row(1, 19), row(2, 19.5), row(3, 20.5)], None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].thresholds, (20.0,))

    def test_one_day_dip_does_not_rearm(self):
        result = detect_crossings([row(1, 21), row(2, 19), row(3, 21)], None)
        self.assertEqual(result, [])

    def test_gap_crosses_multiple_levels(self):
        result = detect_crossings([row(1, 18), row(2, 19), row(3, 31)], None)
        self.assertEqual(result[0].thresholds, (20.0, 25.0, 30.0))

    def test_after_date_prevents_duplicate(self):
        result = detect_crossings(
            [row(1, 18), row(2, 19), row(3, 21)],
            after_date=date(2026, 1, 3),
        )
        self.assertEqual(result, [])

    def test_message_contains_levels_and_closes(self):
        crossing = detect_crossings([row(1, 18), row(2, 19), row(3, 31)], None)
        title, body = build_message(crossing)
        self.assertIn("20、25、30", title)
        self.assertIn("18.00 → 19.00", body)
        self.assertIn("31.00", body)


if __name__ == "__main__":
    unittest.main()

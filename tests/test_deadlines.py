from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.utils.deadlines import extract_deadline_info


class DeadlineParsingTests(unittest.TestCase):
    def test_parses_labeled_close_date(self) -> None:
        info = extract_deadline_info(
            "Placed On: 1st April 2026\nCloses: 28th April 2026\nJob Ref: KA49171",
            today=date(2026, 4, 2),
        )
        self.assertEqual(info.label, "fixed deadline")
        self.assertEqual(info.date_value, date(2026, 4, 28))
        self.assertEqual(info.days_left, 26)

    def test_parses_open_and_close_date(self) -> None:
        info = extract_deadline_info(
            "Open date: 26 February 2026\nClose date: 28 May 2026",
            today=date(2026, 4, 2),
        )
        self.assertEqual(info.date_value, date(2026, 5, 28))

    def test_does_not_fallback_to_first_unlabeled_date(self) -> None:
        info = extract_deadline_info(
            "Posted on 31 March 2026. Review begins on 8 April 2026.",
            today=date(2026, 4, 2),
        )
        self.assertIn(info.label, {"review begins on", "unknown deadline"})
        self.assertNotEqual(info.date_value, date(2026, 3, 31))


if __name__ == "__main__":
    unittest.main()

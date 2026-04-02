from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.models import Opportunity
from academic_discovery.utils.dedupe import deduplicate


class DedupeTests(unittest.TestCase):
    def test_specialized_source_wins_over_generic_source(self) -> None:
        generic = Opportunity(
            type="fellowship",
            title="Funding opportunity: Mathematical sciences postdoctoral fellowship",
            institution="Engineering and Physical Sciences Research Council (EPSRC)",
            department="",
            location="",
            country="United Kingdom",
            salary="",
            posted_date="",
            application_deadline="2026-06-01",
            deadline_status="fixed deadline",
            days_left=None,
            url="https://www.ukri.org/opportunity/?filter_council=epsrc",
            source_site="www.ukri.org",
            source_key="ukri_opportunities_v1",
            summary="Generic listing page",
            eligibility="",
        )
        specialized = Opportunity(
            type="fellowship",
            title="Funding opportunity: Mathematical sciences postdoctoral fellowship",
            institution="Engineering and Physical Sciences Research Council (EPSRC)",
            department="",
            location="",
            country="United Kingdom",
            salary="",
            posted_date="",
            application_deadline="2026-06-01",
            deadline_status="fixed deadline",
            days_left=None,
            url="https://www.ukri.org/opportunity/mathematical-sciences-postdoctoral-fellowship/",
            source_site="www.ukri.org",
            source_key="ukri_epsrc_fellowships_v1",
            summary="Specific fellowship detail page",
            eligibility="",
        )
        items = deduplicate([generic, specialized])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_key, "ukri_epsrc_fellowships_v1")
        self.assertIn("/mathematical-sciences-postdoctoral-fellowship/", items[0].url)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.fetchers.imperial_jobs import _extract_listing_items, _title_from_url
from academic_discovery.fetchers.jobs_ac_uk import _extract_detail_meta
from academic_discovery.fetchers.royal_society_grants import _royal_society_deadline
from bs4 import BeautifulSoup


class FetcherHelperTests(unittest.TestCase):
    def test_jobs_ac_detail_meta_reads_placed_on_and_closes(self) -> None:
        soup = BeautifulSoup(
            """
            <table>
              <tr><th>Placed On</th><td>1st April 2026</td></tr>
              <tr><th>Closes</th><td>28th April 2026</td></tr>
              <tr><th>Salary</th><td>£33,951 to £39,906</td></tr>
            </table>
            """,
            "html.parser",
        )
        meta = _extract_detail_meta(soup)
        self.assertEqual(meta["placed_on"], "1 April 2026")
        self.assertEqual(meta["closes"], "28 April 2026")

    def test_imperial_title_from_url(self) -> None:
        title = _title_from_url(
            "https://www.imperial.ac.uk/jobs/search-jobs/description/index.php?jobId=27506&jobTitle=Imperial+Research+Fellowship"
        )
        self.assertEqual(title, "Imperial Research Fellowship")

    def test_imperial_listing_items_extracts_job_links(self) -> None:
        soup = BeautifulSoup(
            """
            <div>
              <a href="/jobs/search-jobs/description/index.php?jobId=27531&jobTitle=Customer+Service+Manager">Customer Service Manager</a>
              <div>Job Advertisement title Customer Service Manager Salary or Salary range £41,005 - £45,616 per annum 15 Apr 2026 See job details</div>
            </div>
            """,
            "html.parser",
        )
        items = _extract_listing_items(soup, "https://www.imperial.ac.uk/jobs/search-jobs/", 10)
        self.assertEqual(len(items), 1)
        self.assertIn("jobId=27531", items[0]["url"])

    def test_royal_society_deadline_prefers_close_date(self) -> None:
        info = _royal_society_deadline(
            "Open date: 26 February 2026 Close date: 28 May 2026",
            "",
        )
        self.assertEqual(info.date_value.isoformat(), "2026-05-28")


if __name__ == "__main__":
    unittest.main()

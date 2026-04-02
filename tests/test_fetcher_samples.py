from __future__ import annotations

import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.fetchers.cambridge_jobs import CambridgeJobsFetcher
from academic_discovery.fetchers.imperial_fellowships import ImperialFellowshipsFetcher
from academic_discovery.fetchers.leverhulme_listings import LeverhulmeListingsFetcher
from academic_discovery.fetchers.oxford_jobs import OxfordJobsFetcher
from academic_discovery.fetchers.royal_society_grants import RoyalSocietyGrantsFetcher
from academic_discovery.fetchers.ukri_opportunities import UKRIOpportunitiesFetcher


class FetcherSampleTests(unittest.TestCase):
    def test_cambridge_detail_extracts_deadline(self) -> None:
        fetcher = CambridgeJobsFetcher("https://www.cam.ac.uk/jobs/search?search_api_views_fulltext=")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>University Assistant Professor in Civil Engineering</h1>
              <main>
                Date published 01 April 2026 Closing date 11 May 2026
                Department/location Department of Engineering Salary £45,000
                Applicants should have a strong background in structural engineering.
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {
            "url": "https://www.cam.ac.uk/jobs/university-assistant-professor-civil-eng-ab12345",
            "title": "University Assistant Professor in Civil Engineering",
            "department": "Department of Engineering",
            "salary": "£45,000",
            "category": "Academic",
            "posted_date": "01 April 2026",
            "closing_date": "11 May 2026",
        }
        result = fetcher._extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.application_deadline, "2026-05-11")

    def test_oxford_detail_extracts_title_and_deadline(self) -> None:
        fetcher = OxfordJobsFetcher("https://eng.ox.ac.uk/jobs")
        soup = BeautifulSoup(
            """
            <html><body>
              <title>Current vacancies Job Detail ENGINEERING SCIENCE Careers Postdoctoral Research Assistant Salary</title>
              <main>
                Current vacancies Job Detail ENGINEERING SCIENCE Careers Postdoctoral Research Assistant Salary £38,000
                Date published 01 April 2026 Closing date 28 April 2026 Description Research in structural mechanics.
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://eng.ox.ac.uk/jobs/job-detail/123", "title": "Postdoctoral Research Assistant", "closing_date": "28 April 2026"}
        result = fetcher._extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.title, "Postdoctoral Research Assistant")
        self.assertEqual(result.application_deadline, "2026-04-28")

    def test_ukri_detail_extracts_fellowship_deadline(self) -> None:
        fetcher = UKRIOpportunitiesFetcher("https://www.ukri.org/opportunity/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Materials Innovation Programme Coordination Network Pluses</h1>
              <main>
                Opportunity status: Open Opening date: 1 April 2026 Closing date: 27 May 2026
                Publication date 01 April 2026 Funding type Grant Award range £50,000
                Apply for funding to support materials innovation.
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://www.ukri.org/opportunity/materials-innovation/", "title": "Materials Innovation Programme Coordination Network Pluses", "listing_text": "Opportunity status: Open Opening date: 1 April 2026 Closing date: 27 May 2026"}
        result = fetcher._extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.application_deadline, "2026-05-27")

    def test_royal_society_detail_prefers_close_date(self) -> None:
        fetcher = RoyalSocietyGrantsFetcher("https://royalsociety.org/grants/search/grant-listings/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Short Industry Fellowship</h1>
              <main>
                Open date: 26 February 2026 Close date: 28 May 2026
                About the scheme Support researchers to collaborate with industry.
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://royalsociety.org/grants/short-industry-fellowship/", "title": "Short Industry Fellowship", "listing_text": ""}
        result = fetcher._extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.application_deadline, "2026-05-28")

    def test_leverhulme_detail_extracts_key_dates_block(self) -> None:
        fetcher = LeverhulmeListingsFetcher("https://www.leverhulme.ac.uk/listings?field_grant_scheme_target_id=1")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Early Career Fellowships</h1>
              <main>
                Key dates Opening date 01 January 2026 Closing date 20 February 2026 Making an application
                For early career researchers in any discipline.
              </main>
            </body></html>
            """,
            "html.parser",
        )
        result = fetcher._extract_detail("https://www.leverhulme.ac.uk/early-career-fellowships", soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.application_deadline, "2026-02-20")

    def test_imperial_fellowships_table_extracts_rows(self) -> None:
        fetcher = ImperialFellowshipsFetcher(
            "https://www.imperial.ac.uk/early-career-researcher-institute/careers-and-transitions/academic-career-paths/fellowship-opportunities/"
        )
        html = """
        <html><body>
          <table>
            <tr>
              <td><a href="https://www.ukri.org/opportunity/flf/">UKRI - Future Leaders Fellowships</a></td>
              <td>Early career researchers and innovators with outstanding potential.</td>
              <td>Up to 7 years</td>
              <td>Opened: 1 February 2026 Closed: 1 June 2026</td>
            </tr>
          </table>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        fetcher.soup = lambda url: soup
        items = fetcher.fetch()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "UKRI - Future Leaders Fellowships")
        self.assertEqual(items[0].application_deadline, "2026-06-01")


if __name__ == "__main__":
    unittest.main()

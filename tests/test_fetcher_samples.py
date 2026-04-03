from __future__ import annotations

import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.fetchers.academicjobsonline_jobs import AcademicJobsOnlineFetcher
from academic_discovery.fetchers.cambridge_jobs import CambridgeJobsFetcher
from academic_discovery.fetchers.epfl_jobs import EPFLJobsFetcher
from academic_discovery.fetchers.eth_jobs import ETHJobsFetcher
from academic_discovery.fetchers.euraxess_jobs import EuraxessJobsFetcher
from academic_discovery.fetchers.imperial_fellowships import ImperialFellowshipsFetcher
from academic_discovery.fetchers.kuleuven_jobs import KULeuvenJobsFetcher
from academic_discovery.fetchers.leverhulme_listings import LeverhulmeListingsFetcher
from academic_discovery.fetchers.melbourne_jobs import MelbourneJobsFetcher
from academic_discovery.fetchers.nus_jobs import NUSJobsFetcher
from academic_discovery.fetchers.oxford_jobs import OxfordJobsFetcher
from academic_discovery.fetchers.royal_society_grants import RoyalSocietyGrantsFetcher
from academic_discovery.fetchers.tudelft_jobs import TUDelftJobsFetcher
from academic_discovery.fetchers.unsw_jobs import UNSWJobsFetcher
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

    def test_euraxess_detail_extracts_company_and_deadline(self) -> None:
        fetcher = EuraxessJobsFetcher("https://euraxess.ec.europa.eu/jobs")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Postdoctoral Researcher in Hydrogen Materials</h1>
              <main>
                Organisation/Company KU Leuven Department Department of Materials Engineering
                Country Belgium Application Deadline 22 Dec 2026 - 23:59 (Europe/Brussels)
                Posted on 18 Dec 2026 Offer Description The project studies sustainable hydrogen storage materials.
                Requirements Applicants should have a PhD in materials science.
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://euraxess.ec.europa.eu/jobs/302288", "title": "Postdoctoral Researcher in Hydrogen Materials", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.institution, "KU Leuven")
        self.assertEqual(result.application_deadline, "2026-12-22")

    def test_epfl_detail_extracts_title_and_location(self) -> None:
        fetcher = EPFLJobsFetcher("https://careers.epfl.ch/go/Personnel-Scientifique/504674/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Postdoctoral researcher in sustainable structures</h1>
              <main>
                Publication date 01 April 2026 School School of Architecture, Civil and Environmental Engineering
                Description The role focuses on computational mechanics and sustainable structures.
                Profile Applicants should have experience in structural engineering and simulation.
                Location Lausanne Deadline 30 April 2026
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://careers.epfl.ch/job/Lausanne-Postdoctoral-researcher/1234/", "title": "Postdoctoral researcher in sustainable structures", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.location, "Lausanne")
        self.assertEqual(result.application_deadline, "2026-04-30")

    def test_eth_detail_extracts_subtitle_location(self) -> None:
        fetcher = ETHJobsFetcher("https://www.jobs.ethz.ch/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Postdoctoral researcher in computational mechanics</h1>
              <h4>100%, Zurich, fixed-term</h4>
              <main>
                Published 02 April 2026 Project background The role combines finite element modelling and fracture mechanics.
                Profile Applicants should hold a doctorate in civil or mechanical engineering.
                Apply by 28 April 2026
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://www.jobs.ethz.ch/job/view/10929", "title": "Postdoctoral researcher in computational mechanics", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.location, "Zurich")
        self.assertEqual(result.application_deadline, "2026-04-28")

    def test_academicjobsonline_detail_extracts_position_title(self) -> None:
        fetcher = AcademicJobsOnlineFetcher("https://academicjobsonline.org/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h2>University of Pittsburgh, Mechanical Engineering and Materials Science</h2>
              <main>
                Position Title: Department Chair - Mechanical Engineering & Materials Science
                Position Type: Tenured/Tenure-track faculty
                Position Location: Pittsburgh, Pennsylvania 15213, United States of America
                Subject Areas: Mechanical Engineering, Materials Science
                Appl Deadline: (posted 2026/01/19, listed until 2026/02/28)
                Position Description The department seeks a scholar with strong leadership and materials expertise.
                Qualifications Candidates should have an outstanding research record.
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://academicjobsonline.org/ajo/jobs/31245", "title": "", "listing_text": ""}
        result = fetcher._extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.title, "Department Chair - Mechanical Engineering & Materials Science")
        self.assertEqual(result.application_deadline, "2026-02-28")

    def test_nus_detail_extracts_department_and_summary(self) -> None:
        fetcher = NUSJobsFetcher("https://careers.nus.edu.sg/NUS/go/Research-%26-Other-Teaching-Positions-All/733244/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Research Fellow (Hydrogen Systems)</h1>
              <main>
                Department Department of Civil and Environmental Engineering
                Location Singapore Posting Date 01 April 2026
                Job Description Conduct research on hydrogen systems integration and resilient infrastructure.
                Qualifications PhD in civil engineering, energy systems, or related field.
                Application deadline 30 April 2026
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://careers.nus.edu.sg/job/Singapore-Research-Fellow-Hydrogen-Systems/123456", "title": "Research Fellow (Hydrogen Systems)", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.department, "Department of Civil and Environmental Engineering")
        self.assertEqual(result.application_deadline, "2026-04-30")

    def test_unsw_detail_extracts_salary_and_deadline(self) -> None:
        fetcher = UNSWJobsFetcher("https://external-careers.jobs.unsw.edu.au/en/search/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Research Associate in Sustainable Structures</h1>
              <main>
                Faculty Faculty of Engineering Location Sydney, NSW
                Remuneration $123,000 - $145,000
                About the role Lead computational mechanics research for sustainable structures.
                Skills and Experience Experience in structural engineering and simulation.
                Applications close 07 May 2026
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://external-careers.jobs.unsw.edu.au/en/job/534141/research-associate-in-sustainable-structures", "title": "Research Associate in Sustainable Structures", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.salary, "$123,000 - $145,000")
        self.assertEqual(result.application_deadline, "2026-05-07")

    def test_kuleuven_detail_extracts_department_and_deadline(self) -> None:
        fetcher = KULeuvenJobsFetcher("https://www.kuleuven.be/personeel/jobsite/en/academic-staff")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Postdoctoral researcher in structural materials</h1>
              <main>
                Department Department of Civil Engineering
                Location Leuven
                Offer The project focuses on hydrogen-material interactions in structural materials.
                Profile Applicants should have a PhD in civil engineering or materials science.
                Apply by 14 May 2026
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://www.kuleuven.be/personeel/jobsite/jobs/604321", "title": "Postdoctoral researcher in structural materials", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.department, "Department of Civil Engineering")
        self.assertEqual(result.application_deadline, "2026-05-14")
        prefixed = fetcher.extract_detail(
            {"url": "https://www.kuleuven.be/personeel/jobsite/jobs/60651402?lang=en", "title": "", "listing_text": "2026-05-14"},
            BeautifulSoup(
                "<html><body><title>KU Leuven Vacancies | PhD position in Finance</title><main>Profile text</main></body></html>",
                "html.parser",
            ),
        )
        self.assertEqual(prefixed.title, "PhD position in Finance")

    def test_tudelft_detail_extracts_title_and_deadline(self) -> None:
        fetcher = TUDelftJobsFetcher("https://careers.tudelft.nl/")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Postdoc Researcher in Circular Structures</h1>
              <main>
                Faculty Faculty of Civil Engineering and Geosciences
                Location Delft
                Published 03 April 2026
                Job description Research on circular structural systems and computational design.
                Job requirements PhD in civil engineering, structures, or related field.
                Closing date 30 April 2026
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://careers.tudelft.nl/job/Delft-Postdoc-Researcher-in-Circular-Structures/1348720857", "title": "Postdoc Researcher in Circular Structures", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.location, "Delft")
        self.assertEqual(result.application_deadline, "2026-04-30")

    def test_melbourne_detail_extracts_salary_and_deadline(self) -> None:
        fetcher = MelbourneJobsFetcher("https://jobs.unimelb.edu.au/en/search/?search-keyword=research")
        soup = BeautifulSoup(
            """
            <html><body>
              <h1>Research Fellow in Sustainable Infrastructure</h1>
              <main>
                Faculty Faculty of Engineering and Information Technology
                Location Melbourne
                Salary $122,000 - $145,000
                About the Role Conduct research in sustainable infrastructure and simulation-driven design.
                Who We Are Looking For A candidate with a PhD in civil engineering or related area.
                Applications close 28 May 2026
              </main>
            </body></html>
            """,
            "html.parser",
        )
        item = {"url": "https://jobs.unimelb.edu.au/en/job/919357/research-fellow-in-sustainable-infrastructure", "title": "Research Fellow in Sustainable Infrastructure", "listing_text": ""}
        result = fetcher.extract_detail(item, soup)
        self.assertIsNotNone(result)
        self.assertEqual(result.salary, "$122,000 - $145,000")
        self.assertEqual(result.application_deadline, "2026-05-28")


if __name__ == "__main__":
    unittest.main()

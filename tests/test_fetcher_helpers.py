from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.config import normalize_config
from academic_discovery.fetchers.base import DynamicListDetailFetcher
from academic_discovery.fetchers.imperial_jobs import _extract_listing_items, _title_from_url
from academic_discovery.fetchers.jobs_ac_uk import _extract_detail_meta
from academic_discovery.fetchers.royal_society_grants import _royal_society_deadline
from academic_discovery.source_registry import resolve_sources
from bs4 import BeautifulSoup


class _DummyDynamicFetcher(DynamicListDetailFetcher):
    def __init__(self) -> None:
        super().__init__()
        self.base_url = "https://example.com/jobs"

    def playwright_available(self) -> bool:
        return False

    def collect_items_static(self) -> list[dict[str, str]]:
        return [{"url": "https://example.com/jobs/1", "title": "Example"}]

    def collect_items_dynamic(self) -> list[dict[str, str]]:
        return []

    def fetch_dynamic_details(self, detail_items: list[dict[str, str]]) -> list:
        return []

    def fetch_static_details(self, detail_items: list[dict[str, str]]) -> list:
        self.update_diagnostics(detail_success=len(detail_items), detail_failed=0, parser_failures=0)
        return detail_items


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

    def test_dynamic_fetcher_falls_back_to_static_mode(self) -> None:
        fetcher = _DummyDynamicFetcher()
        items = fetcher.fetch()
        diagnostics = fetcher.diagnostics()
        self.assertEqual(len(items), 1)
        self.assertTrue(diagnostics["dynamic_source"])
        self.assertTrue(diagnostics["fallback_used"])
        self.assertEqual(diagnostics["fetch_mode"], "static")

    def test_normalize_config_builds_sources_from_legacy_sections(self) -> None:
        config = normalize_config(
            {
                "cv_pdf": "data/cv.pdf",
                "output_dir": "output",
                "keywords": ["hydrogen"],
                "jobs_ac_uk": {
                    "enabled": True,
                    "base_url": "https://www.jobs.ac.uk/search/",
                    "queries": ["civil-engineering"],
                    "max_pages": 2,
                },
                "generic_targets": [
                    {
                        "name": "Example Fellowships",
                        "url": "https://example.com/fellowships",
                        "type": "fellowship",
                        "keywords": ["fellowship"],
                    }
                ],
            }
        )
        self.assertIn("sources", config)
        self.assertTrue(config["sources"]["jobs_ac_uk"]["enabled"])
        self.assertEqual(config["sources"]["jobs_ac_uk"]["params"]["queries"], ["civil-engineering"])
        self.assertEqual(len(config["sources"]["generic"]), 1)

    def test_resolve_sources_returns_registry_entries(self) -> None:
        config = normalize_config(
            {
                "cv_pdf": "data/cv.pdf",
                "output_dir": "output",
                "keywords": ["hydrogen"],
                "sources": {
                    "jobs_ac_uk": {
                        "enabled": True,
                        "base_url": "https://www.jobs.ac.uk/search/",
                        "params": {
                            "queries": ["materials-engineering"],
                            "max_pages": 1,
                        },
                    },
                    "generic": [
                        {
                            "enabled": True,
                            "name": "Example Generic",
                            "url": "https://example.com/jobs",
                            "type": "job",
                            "keywords": ["job"],
                        }
                    ],
                },
            }
        )
        sources = resolve_sources(config)
        keys = {item.source_key for item in sources}
        self.assertIn("jobs_ac_uk_v3", keys)
        self.assertTrue(any(item.config_section == "generic" for item in sources))

    def test_resolve_sources_supports_new_international_registry_entries(self) -> None:
        config = normalize_config(
            {
                "cv_pdf": "data/cv.pdf",
                "output_dir": "output",
                "sources": {
                    "epfl_jobs": {
                        "enabled": True,
                        "base_url": "https://careers.epfl.ch/go/Personnel-Scientifique/504674/",
                        "params": {"max_results": 20},
                    },
                    "eth_jobs": {
                        "enabled": True,
                        "base_url": "https://www.jobs.ethz.ch/",
                        "params": {"max_results": 20},
                    },
                    "academicjobsonline_jobs": {
                        "enabled": True,
                        "base_url": "https://academicjobsonline.org/",
                        "params": {
                            "boards": ["https://academicjobsonline.org/ajo/Eng/Materials%20Science"],
                            "max_results": 25,
                        },
                    },
                },
            }
        )
        sources = resolve_sources(config)
        keys = {item.source_key for item in sources}
        self.assertIn("epfl_jobs_v1", keys)
        self.assertIn("eth_jobs_v1", keys)
        self.assertIn("academicjobsonline_jobs_v1", keys)

    def test_resolve_sources_supports_next_batch_registry_entries(self) -> None:
        config = normalize_config(
            {
                "cv_pdf": "data/cv.pdf",
                "output_dir": "output",
                "sources": {
                    "kuleuven_jobs": {
                        "enabled": True,
                        "base_url": "https://www.kuleuven.be/personeel/jobsite/en/academic-staff",
                    },
                    "tudelft_jobs": {
                        "enabled": True,
                        "base_url": "https://careers.tudelft.nl/",
                    },
                    "melbourne_jobs": {
                        "enabled": True,
                        "base_url": "https://jobs.unimelb.edu.au/en/search/?search-keyword=research",
                    },
                },
            }
        )
        keys = {item.source_key for item in resolve_sources(config)}
        self.assertIn("kuleuven_jobs_v3", keys)
        self.assertIn("tudelft_jobs_v3", keys)
        self.assertIn("melbourne_jobs_v1", keys)


if __name__ == "__main__":
    unittest.main()

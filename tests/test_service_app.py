from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.db import initialize_database, record_pipeline_run, sync_current_opportunities

try:
    from fastapi.testclient import TestClient
    from academic_discovery.webapp import create_app
    FASTAPI_TESTS_AVAILABLE = True
    FASTAPI_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - environment-dependent optional import
    TestClient = None
    create_app = None
    FASTAPI_TESTS_AVAILABLE = False
    FASTAPI_IMPORT_ERROR = str(exc)


@unittest.skipUnless(FASTAPI_TESTS_AVAILABLE, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class ServiceAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_dir = Path(tempfile.gettempdir()) / "AcademicDiscoveryServiceTests" / next(tempfile._get_candidate_names())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = self.base_dir / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = self.data_dir / "service_test.db"
        self.config_path = self.base_dir / "config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "cv_pdf": str(self.base_dir / "cv.pdf"),
                    "output_dir": str(self.output_dir),
                    "database_path": str(self.database_path),
                    "keywords": ["hydrogen"],
                    "filters": {"include_types": ["job", "fellowship"]},
                }
            ),
            encoding="utf-8",
        )
        (self.base_dir / "cv.pdf").write_bytes(b"%PDF-1.4\n%stub\n")
        initialize_database(self.database_path)
        sync_current_opportunities(
            self.database_path,
            [
                {
                    "url": "https://example.com/jobs/1",
                    "type": "job",
                    "title": "Research Associate in Hydrogen Materials",
                    "institution": "Example University",
                    "source_site": "example.com",
                    "source_key": "example_jobs_v1",
                }
            ],
        )
        record_pipeline_run(
            self.database_path,
            opportunities_found=1,
            opportunities_saved=1,
            new_jobs=1,
            new_fellowships=0,
            diagnostics_json=json.dumps(
                {
                    "sources": [
                        {
                            "source_key": "example_jobs_v1",
                            "status": "fetched",
                            "cache_hit": False,
                            "items_count": 1,
                            "filtered_count": 0,
                            "detail_success": 1,
                            "detail_failed": 0,
                            "error": "",
                        }
                    ]
                }
            ),
        )

    def test_health_and_system_state_endpoints(self) -> None:
        app = create_app(output_dir=self.output_dir, config_path=self.config_path, refresh_on_start=False)
        with TestClient(app) as client:
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["ok"])

            state = client.get("/api/system-state")
            self.assertEqual(state.status_code, 200)
            payload = state.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["source_health"]), 1)

            opportunities = client.get("/api/opportunities")
            self.assertEqual(opportunities.status_code, 200)
            items = opportunities.json()["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Research Associate in Hydrogen Materials")

    def test_manual_override_and_reset_endpoints(self) -> None:
        app = create_app(output_dir=self.output_dir, config_path=self.config_path, refresh_on_start=False)
        with TestClient(app) as client:
            save = client.post(
                "/api/opportunity-override",
                json={
                    "url": "https://example.com/jobs/1",
                    "field": "application_deadline",
                    "value": "2026-05-20",
                },
            )
            self.assertEqual(save.status_code, 200)

            opportunities = client.get("/api/opportunities")
            item = opportunities.json()["items"][0]
            self.assertEqual(item["application_deadline"], "2026-05-20")
            self.assertEqual(item["original_application_deadline"], "")
            self.assertIn("application_deadline", item["manual_override_fields"])

            reset = client.post(
                "/api/opportunity-override/reset",
                json={"url": "https://example.com/jobs/1", "field": "application_deadline"},
            )
            self.assertEqual(reset.status_code, 200)
            item = client.get("/api/opportunities").json()["items"][0]
            self.assertEqual(item["application_deadline"], "")
            self.assertNotIn("application_deadline", item["manual_override_fields"])

    def test_note_endpoint_and_validation(self) -> None:
        app = create_app(output_dir=self.output_dir, config_path=self.config_path, refresh_on_start=False)
        with TestClient(app) as client:
            note_response = client.post(
                "/api/opportunity-note",
                json={
                    "url": "https://example.com/jobs/1",
                    "field": "note",
                    "value": "Worth checking with battery projects",
                },
            )
            self.assertEqual(note_response.status_code, 200)
            item = client.get("/api/opportunities").json()["items"][0]
            self.assertEqual(item["note"], "Worth checking with battery projects")
            self.assertIn("note", item["manual_override_fields"])

            invalid_field = client.post(
                "/api/opportunity-override",
                json={
                    "url": "https://example.com/jobs/1",
                    "field": "salary",
                    "value": "100000",
                },
            )
            self.assertEqual(invalid_field.status_code, 400)

            invalid_date = client.post(
                "/api/opportunity-override",
                json={
                    "url": "https://example.com/jobs/1",
                    "field": "posted_date",
                    "value": "01/04/2026",
                },
            )
            self.assertEqual(invalid_date.status_code, 400)

            missing_url = client.post(
                "/api/opportunity-note",
                json={"url": "", "field": "note", "value": "x"},
            )
            self.assertEqual(missing_url.status_code, 400)


if __name__ == "__main__":
    unittest.main()

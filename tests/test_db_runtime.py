from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from academic_discovery.db import (
    export_sync_database,
    export_runtime_state,
    import_sync_database,
    initialize_database,
    read_archived_opportunities,
    read_combined_opportunities,
    read_current_opportunities,
    read_saved_statuses,
    reset_manual_override,
    restore_saved_statuses,
    run_startup_migrations,
    set_manual_override,
    set_saved_status,
    sync_current_opportunities,
    undo_last_status_change,
)


class DatabaseRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        base_dir = Path(tempfile.gettempdir()) / "AcademicDiscoveryTests"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = base_dir
        self.database_path = base_dir / f"{uuid4().hex}.db"
        self.addCleanup(lambda: _safe_unlink(self.database_path))
        initialize_database(self.database_path)

    def test_sync_preserves_saved_status_and_exports(self) -> None:
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/1",
            status="applied",
            meta={"type": "fellowship", "title": "Imperial Research Fellowship", "institution": "Imperial College London"},
        )
        rows = sync_current_opportunities(
            self.database_path,
            [
                {
                    "url": "https://example.com/jobs/1",
                    "type": "fellowship",
                    "title": "Imperial Research Fellowship",
                    "institution": "Imperial College London",
                    "application_deadline": "2026-07-23",
                    "deadline_status": "fixed deadline",
                    "source_site": "www.imperial.ac.uk",
                }
            ],
        )
        self.assertEqual(rows[0]["status"], "applied")
        current = read_current_opportunities(self.database_path)
        self.assertEqual(current[0]["status"], "applied")

        output_dir = self.temp_dir / f"output-{uuid4().hex}"
        self.addCleanup(lambda: output_dir.exists() and __import__("shutil").rmtree(output_dir, ignore_errors=True))
        export_runtime_state(output_dir, self.database_path)
        self.assertTrue((output_dir / "jobs.csv").exists() or (output_dir / "fellowships.csv").exists())
        self.assertTrue((output_dir / "statuses.csv").exists())

    def test_archives_saved_status_when_opportunity_missing_from_current_run(self) -> None:
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/archive-me",
            status="applied",
            meta={"type": "fellowship", "title": "Imperial Research Fellowship", "institution": "Imperial College London"},
        )
        sync_current_opportunities(
            self.database_path,
            [
                {
                    "url": "https://example.com/jobs/active",
                    "type": "job",
                    "title": "Research Associate",
                    "institution": "Example University",
                    "source_site": "example.com",
                }
            ],
        )
        archived = {row["url"]: row for row in read_archived_opportunities(self.database_path)}
        self.assertIn("https://example.com/jobs/archive-me", archived)
        self.assertEqual(archived["https://example.com/jobs/archive-me"]["status"], "applied")

    def test_undo_restores_previous_status(self) -> None:
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/2",
            status="interested",
            meta={"type": "job", "title": "Research Associate", "institution": "Example University"},
        )
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/2",
            status="applied",
            meta={"type": "job", "title": "Research Associate", "institution": "Example University"},
        )
        result = undo_last_status_change(self.database_path)
        self.assertTrue(result["undone"])
        saved = {row["url"]: row for row in read_saved_statuses(self.database_path)}
        self.assertEqual(saved["https://example.com/jobs/2"]["status"], "interested")

    def test_restore_saved_statuses_recovers_missing_current_status(self) -> None:
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/3",
            status="ignored",
            meta={"type": "job", "title": "Research Fellow", "institution": "Example University"},
        )
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/3",
            status="",
            meta={"type": "job", "title": "Research Fellow", "institution": "Example University"},
        )
        restored = restore_saved_statuses(self.database_path)
        self.assertGreaterEqual(restored, 1)
        saved = {row["url"]: row for row in read_saved_statuses(self.database_path)}
        self.assertEqual(saved["https://example.com/jobs/3"]["status"], "ignored")

    def test_startup_migration_imports_csv_once(self) -> None:
        output_dir = self.temp_dir / f"migration-{uuid4().hex}"
        output_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: output_dir.exists() and __import__("shutil").rmtree(output_dir, ignore_errors=True))
        (output_dir / "statuses.csv").write_text(
            "url,status,note,type,title,institution\n"
            "https://example.com/jobs/4,interested,,job,Research Fellow,Example University\n",
            encoding="utf-8",
        )
        (output_dir / "status_history.csv").write_text(
            "timestamp,url,previous_status,new_status,type,title,institution\n"
            "2026-04-02T12:00:00,https://example.com/jobs/4,,interested,job,Research Fellow,Example University\n",
            encoding="utf-8",
        )
        run_startup_migrations(output_dir, self.database_path)
        run_startup_migrations(output_dir, self.database_path)
        saved = {row["url"]: row for row in read_saved_statuses(self.database_path)}
        self.assertEqual(saved["https://example.com/jobs/4"]["status"], "interested")

    def test_sync_database_export_and_import(self) -> None:
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/sync",
            status="applied",
            meta={"type": "job", "title": "Sync Candidate", "institution": "Example University"},
        )
        sync_path = self.temp_dir / f"sync-{uuid4().hex}.db"
        self.addCleanup(lambda: _safe_unlink(sync_path))
        exported = export_sync_database(self.database_path, sync_path)
        self.assertTrue(exported["exported"])

        target_path = self.temp_dir / f"import-{uuid4().hex}.db"
        self.addCleanup(lambda: _safe_unlink(target_path))
        imported = import_sync_database(target_path, sync_path)
        self.assertTrue(imported["imported"])
        saved = {row["url"]: row for row in read_saved_statuses(target_path)}
        self.assertEqual(saved["https://example.com/jobs/sync"]["status"], "applied")

    def test_manual_override_applies_and_resets(self) -> None:
        sync_current_opportunities(
            self.database_path,
            [
                {
                    "url": "https://example.com/jobs/override",
                    "type": "job",
                    "title": "Research Associate",
                    "institution": "Example University",
                    "posted_date": "2026-04-01",
                    "application_deadline": "2026-04-28",
                    "source_site": "example.com",
                }
            ],
        )
        set_manual_override(
            self.database_path,
            url="https://example.com/jobs/override",
            field="application_deadline",
            value="2026-05-15",
        )
        rows = {row["url"]: row for row in read_combined_opportunities(self.database_path)}
        row = rows["https://example.com/jobs/override"]
        self.assertEqual(row["application_deadline"], "2026-05-15")
        self.assertEqual(row["original_application_deadline"], "2026-04-28")
        self.assertIn("application_deadline", row["manual_override_fields"])

        reset_manual_override(
            self.database_path,
            url="https://example.com/jobs/override",
            field="application_deadline",
        )
        rows = {row["url"]: row for row in read_combined_opportunities(self.database_path)}
        row = rows["https://example.com/jobs/override"]
        self.assertEqual(row["application_deadline"], "2026-04-28")
        self.assertNotIn("application_deadline", row["manual_override_fields"])

    def test_manual_note_persists_for_archived_items(self) -> None:
        set_saved_status(
            self.database_path,
            url="https://example.com/jobs/archive-note",
            status="interested",
            meta={"type": "fellowship", "title": "Archive Fellowship", "institution": "Example University"},
        )
        sync_current_opportunities(
            self.database_path,
            [
                {
                    "url": "https://example.com/jobs/active-only",
                    "type": "job",
                    "title": "Current Job",
                    "institution": "Example University",
                    "source_site": "example.com",
                }
            ],
        )
        set_manual_override(
            self.database_path,
            url="https://example.com/jobs/archive-note",
            field="note",
            value="Check supervisor fit before applying",
        )
        rows = {row["url"]: row for row in read_combined_opportunities(self.database_path)}
        row = rows["https://example.com/jobs/archive-note"]
        self.assertEqual(row["status"], "interested")
        self.assertEqual(row["note"], "Check supervisor fit before applying")
        self.assertIn("note", row["manual_override_fields"])


if __name__ == "__main__":
    unittest.main()


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        return

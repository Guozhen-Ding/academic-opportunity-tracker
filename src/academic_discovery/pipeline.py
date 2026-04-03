from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, timedelta
from pathlib import Path
from json import dumps
from typing import Any

import pandas as pd

from datetime import date

from academic_discovery.cv import extract_profile_from_pdf
from academic_discovery.db import (
    export_runtime_state,
    default_database_path,
    export_sync_database,
    import_sync_database,
    initialize_database,
    read_display_current_opportunities,
    record_config_snapshot,
    record_pipeline_run,
    run_startup_migrations,
    sync_current_opportunities,
)
from academic_discovery.emailer import send_summary_email
from academic_discovery.models import Opportunity
from academic_discovery.reporting import render_email_summary, write_outputs
from academic_discovery.source_registry import resolve_sources
from academic_discovery.utils.dedupe import deduplicate
from academic_discovery.utils.scoring import (
    DEFAULT_BROAD_TERMS,
    DEFAULT_EXPANDED_TERMS,
    DEFAULT_PROTECTED_TERMS,
    score_opportunity,
    should_keep_opportunity,
)
from academic_discovery.utils.text import normalize_whitespace


@dataclass
class FetchResult:
    source_key: str
    items: list[Opportunity]
    status: str
    cache_hit: bool
    source_name: str = ""
    kind: str = ""
    source_priority: int = 0
    dynamic_source: bool = False
    fallback_used: bool = False
    fetch_mode: str = "static"
    list_count: int = 0
    detail_success: int = 0
    detail_failed: int = 0
    filtered_count: int = 0
    consecutive_failures: int = 0
    last_success_at: str = ""
    parser_failures: int = 0
    error: str = ""

    def to_diagnostic(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "source_name": self.source_name,
            "kind": self.kind,
            "source_priority": self.source_priority,
            "status": self.status,
            "cache_hit": self.cache_hit,
            "dynamic_source": self.dynamic_source,
            "fallback_used": self.fallback_used,
            "fetch_mode": self.fetch_mode,
            "items_count": len(self.items),
            "list_count": self.list_count,
            "detail_success": self.detail_success,
            "detail_failed": self.detail_failed,
            "parser_failures": self.parser_failures,
            "filtered_count": self.filtered_count,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": self.last_success_at,
            "error": self.error,
        }


def run_pipeline(config: dict) -> dict:
    profile = extract_profile_from_pdf(config["cv_pdf"])
    opportunities: list[Opportunity] = []
    source_diagnostics: list[dict[str, Any]] = []
    output_dir = Path(config["output_dir"])
    cache_dir = output_dir / "source_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "fetch_state.json"
    fetch_state = _load_fetch_state(state_path)
    database_path = config.get("database_path") or str(default_database_path(config["output_dir"]))
    sync_database_path = config.get("sync_database_path")
    import_sync_database(database_path, sync_database_path)
    initialize_database(database_path)
    run_startup_migrations(output_dir, database_path)

    for resolved_source in resolve_sources(config):
        result = _fetch_or_load_cached(
            source_key=resolved_source.source_key,
            refresh_hours=resolved_source.refresh_hours,
            fetch_state=fetch_state,
            cache_dir=cache_dir,
            factory=resolved_source.factory,
            source_name=resolved_source.name,
            kind=resolved_source.kind,
            source_priority=resolved_source.source_priority,
            supports_dynamic=resolved_source.supports_dynamic,
        )
        source_diagnostics.append(result.to_diagnostic())
        opportunities.extend(result.items)

    opportunities = deduplicate(opportunities)

    extra_keywords = config.get("keywords", [])
    minimum_score = float(config.get("filters", {}).get("minimum_score", 0.0))
    include_types = set(config.get("filters", {}).get("include_types", ["job", "fellowship"]))
    expanded_terms = list(dict.fromkeys(DEFAULT_EXPANDED_TERMS.union(set(config.get("filters", {}).get("expanded_terms", [])))))
    protected_terms = list(dict.fromkeys(DEFAULT_PROTECTED_TERMS.union(set(config.get("filters", {}).get("protected_terms", [])))))
    broad_terms = list(dict.fromkeys(DEFAULT_BROAD_TERMS.union(set(config.get("filters", {}).get("broad_terms", [])))))
    exclude_terms = [str(term).lower().strip() for term in config.get("filters", {}).get("exclude_terms", []) if str(term).strip()]

    filtered: list[Opportunity] = []
    filter_counts = {
        "excluded_by_type": 0,
        "excluded_by_terms": 0,
        "filtered_out_by_score": 0,
        "kept_by_score": 0,
        "kept_by_protected_terms": 0,
        "kept_by_broad_terms": 0,
        "kept_by_fellowship_rule": 0,
    }
    for item in opportunities:
        item.match_score, item.match_reason, matched_keywords = score_opportunity(item, profile, extra_keywords, expanded_terms)
        item.matched_keywords = ", ".join(matched_keywords)
        if item.type not in include_types:
            filter_counts["excluded_by_type"] += 1
            continue
        haystack = normalize_whitespace(
            " ".join(
                [
                    item.title,
                    item.institution,
                    item.department,
                    item.summary,
                    item.eligibility,
                ]
            )
        ).lower()
        if exclude_terms and any(term in haystack for term in exclude_terms):
            filter_counts["excluded_by_terms"] += 1
            continue
        keep, keep_reason = should_keep_opportunity(
            item,
            score=item.match_score,
            minimum_score=minimum_score,
            protected_terms=protected_terms,
            broad_terms=broad_terms,
        )
        if not keep:
            filter_counts["filtered_out_by_score"] += 1
            continue
        if keep_reason == "Preserved by score":
            filter_counts["kept_by_score"] += 1
        elif keep_reason.startswith("Preserved by protected terms:"):
            filter_counts["kept_by_protected_terms"] += 1
        elif keep_reason.startswith("Preserved by broad academic terms:"):
            filter_counts["kept_by_broad_terms"] += 1
        elif keep_reason == "Preserved by broad rule: fellowship":
            filter_counts["kept_by_fellowship_rule"] += 1
        if keep_reason not in {"Preserved by score"}:
            item.match_reason = f"{item.match_reason} | {keep_reason}"
        filtered.append(item)

    current_records = sync_current_opportunities(
        database_path,
        [item.to_record() if hasattr(item, "to_record") else item for item in filtered],
    )
    filtered = [_record_to_opportunity(record) for record in read_display_current_opportunities(database_path)]

    outputs = write_outputs(
        filtered,
        config["output_dir"],
        config_snapshot={
            "keywords": config.get("keywords", []),
            "exclude_terms": config.get("filters", {}).get("exclude_terms", []),
            "protected_terms": config.get("filters", {}).get("protected_terms", []),
            "expanded_terms": config.get("filters", {}).get("expanded_terms", []),
        },
    )
    export_runtime_state(config["output_dir"], database_path)
    export_sync_database(database_path, sync_database_path)
    source_output_counts: dict[str, int] = {}
    for record in current_records:
        key = str(record.get("source_key", "") or "")
        source_output_counts[key] = source_output_counts.get(key, 0) + 1
    diagnostics_payload = {
        "sources": [
            {
                **diagnostic,
                "saved_after_filter": source_output_counts.get(diagnostic["source_key"], 0),
            }
            for diagnostic in source_diagnostics
        ],
        "filter_counts": filter_counts,
        "database_path": str(database_path),
    }
    database_sync = {
        "ok": False,
        "database_path": str(database_path),
        "synced_at": datetime.utcnow().isoformat(timespec="seconds"),
        "opportunities_current": len(filtered),
        "pipeline_runs_recorded": 0,
        "status_history_imported": False,
        "error": "",
        "diagnostics": diagnostics_payload,
    }
    try:
        record_pipeline_run(
            database_path,
            opportunities_found=len(opportunities),
            opportunities_saved=len(filtered),
            new_jobs=len(outputs["new_jobs"]),
            new_fellowships=len(outputs["new_fellowships"]),
            diagnostics_json=dumps(diagnostics_payload, ensure_ascii=False),
        )
        record_config_snapshot(
            database_path,
            keywords_json=dumps(config.get("keywords", []), ensure_ascii=False),
            exclude_terms_json=dumps(config.get("filters", {}).get("exclude_terms", []), ensure_ascii=False),
            protected_terms_json=dumps(config.get("filters", {}).get("protected_terms", []), ensure_ascii=False),
            expanded_terms_json=dumps(config.get("filters", {}).get("expanded_terms", []), ensure_ascii=False),
        )
        database_sync["ok"] = True
        database_sync["pipeline_runs_recorded"] = 1
        database_sync["status_history_imported"] = True
    except Exception as exc:
        database_sync["error"] = str(exc)
    (output_dir / "database_sync.json").write_text(
        json.dumps(database_sync, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    email_sent = False
    email_error = ""
    email_config = config.get("email")
    legacy_smtp = config.get("smtp", {})
    enabled = bool(email_config.get("enabled")) if email_config else bool(legacy_smtp.get("enabled"))
    if enabled:
        effective_email_config = email_config or {"minimum_score": legacy_smtp.get("minimum_score", minimum_score), "max_items": legacy_smtp.get("max_items", 10), "subject": legacy_smtp.get("subject", "Academic opportunities summary")}
        minimum_email_score = float(effective_email_config.get("minimum_score", minimum_score))
        new_jobs = [item for item in outputs["new_jobs"] if float(item.get("match_score", 0)) >= minimum_email_score]
        new_fellowships = [
            item for item in outputs["new_fellowships"] if float(item.get("match_score", 0)) >= minimum_email_score
        ]
        if new_jobs or new_fellowships:
            email_body = render_email_summary(
                new_jobs=new_jobs,
                new_fellowships=new_fellowships,
                today=date.today(),
                max_items=int(effective_email_config.get("max_items", 10)),
            )
            try:
                email_sent = send_summary_email(
                    config,
                    subject=effective_email_config.get("subject", "Academic opportunities summary"),
                    body=email_body,
                )
            except Exception as exc:
                email_error = str(exc)

    return {
        "profile_keywords": profile.keywords[:20],
        "opportunities_found": len(opportunities),
        "opportunities_saved": len(filtered),
        "new_jobs": len(outputs["new_jobs"]),
        "new_fellowships": len(outputs["new_fellowships"]),
        "email_sent": email_sent,
        "email_error": email_error,
        "outputs": {
            key: str(value)
            for key, value in outputs.items()
            if key in {"jobs", "fellowships", "report", "dashboard"}
        },
    }


def _fetch_or_load_cached(
    source_key: str,
    refresh_hours: float,
    fetch_state: dict[str, dict],
    cache_dir: Path,
    factory,
    source_name: str = "",
    kind: str = "",
    source_priority: int = 0,
    supports_dynamic: bool = False,
) -> FetchResult:
    cache_path = cache_dir / f"{source_key}.csv"
    state = fetch_state.get(source_key, {})
    if _is_cache_fresh(fetch_state, source_key, refresh_hours) and cache_path.exists():
        items = _load_cached_opportunities(cache_path)
        return FetchResult(
            source_key=source_key,
            items=items,
            status="cache_hit",
            cache_hit=True,
            source_name=source_name,
            kind=kind,
            source_priority=source_priority,
            dynamic_source=supports_dynamic,
            list_count=len(items),
            detail_success=len(items),
            consecutive_failures=int(state.get("consecutive_failures", 0) or 0),
            last_success_at=str(state.get("last_success_at", "") or ""),
        )

    try:
        fetcher = factory()
        items = fetcher.fetch()
        fetcher_diagnostics = _extract_fetcher_diagnostics(fetcher)
        for item in items:
            item.source_key = source_key
        _write_cached_opportunities(cache_path, items)
        fetch_state[source_key] = {
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds"),
            "last_success_at": datetime.utcnow().isoformat(timespec="seconds"),
            "count": len(items),
            "consecutive_failures": 0,
            "last_status": "fetched",
            "last_error": "",
        }
        return FetchResult(
            source_key=source_key,
            items=items,
            status="fetched",
            cache_hit=False,
            source_name=source_name,
            kind=kind,
            source_priority=source_priority,
            dynamic_source=bool(fetcher_diagnostics.get("dynamic_source", supports_dynamic)),
            fallback_used=bool(fetcher_diagnostics.get("fallback_used", False)),
            fetch_mode=str(fetcher_diagnostics.get("fetch_mode", "static") or "static"),
            list_count=int(fetcher_diagnostics.get("list_count", len(items)) or len(items)),
            detail_success=int(fetcher_diagnostics.get("detail_success", len(items)) or len(items)),
            detail_failed=int(fetcher_diagnostics.get("detail_failed", 0) or 0),
            parser_failures=int(fetcher_diagnostics.get("parser_failures", 0) or 0),
            consecutive_failures=0,
            last_success_at=str(fetch_state[source_key].get("last_success_at", "") or ""),
            error=str(fetcher_diagnostics.get("error", "") or ""),
        )
    except Exception as exc:
        next_failures = int(state.get("consecutive_failures", 0) or 0) + 1
        if cache_path.exists():
            items = _load_cached_opportunities(cache_path)
            fetch_state[source_key] = {
                **state,
                "consecutive_failures": next_failures,
                "last_status": "cache_fallback_after_error",
                "last_error": str(exc),
            }
            return FetchResult(
                source_key=source_key,
                items=items,
                status="cache_fallback_after_error",
                cache_hit=True,
                source_name=source_name,
                kind=kind,
                source_priority=source_priority,
                dynamic_source=supports_dynamic,
                fallback_used=True,
                fetch_mode="static",
                list_count=len(items),
                detail_success=len(items),
                consecutive_failures=next_failures,
                last_success_at=str(state.get("last_success_at", "") or ""),
                error=str(exc),
            )
        fetch_state[source_key] = {
            **state,
            "consecutive_failures": next_failures,
            "last_status": "fetch_failed",
            "last_error": str(exc),
        }
        return FetchResult(
            source_key=source_key,
            items=[],
            status="fetch_failed",
            cache_hit=False,
            source_name=source_name,
            kind=kind,
            source_priority=source_priority,
            dynamic_source=supports_dynamic,
            fallback_used=False,
            fetch_mode="static",
            consecutive_failures=next_failures,
            last_success_at=str(state.get("last_success_at", "") or ""),
            error=str(exc),
        )
    finally:
        _save_fetch_state(cache_dir.parent / "fetch_state.json", fetch_state)


def _is_cache_fresh(fetch_state: dict[str, dict], source_key: str, refresh_hours: float) -> bool:
    state = fetch_state.get(source_key, {})
    fetched_at = state.get("fetched_at")
    if not fetched_at:
        return False
    try:
        timestamp = datetime.fromisoformat(str(fetched_at))
    except ValueError:
        return False
    return datetime.utcnow() - timestamp < timedelta(hours=refresh_hours)


def _load_fetch_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_fetch_state(path: Path, fetch_state: dict[str, dict]) -> None:
    path.write_text(json.dumps(fetch_state, indent=2), encoding="utf-8")


def _extract_fetcher_diagnostics(fetcher: Any) -> dict[str, Any]:
    try:
        diagnostics = fetcher.diagnostics()
    except Exception:
        diagnostics = {}
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    return diagnostics


def _write_cached_opportunities(path: Path, items: list[Opportunity]) -> None:
    pd.DataFrame([item.to_record() for item in items]).to_csv(path, index=False)


def _load_cached_opportunities(path: Path) -> list[Opportunity]:
    try:
        frame = pd.read_csv(path, keep_default_na=False)
    except Exception:
        return []
    items: list[Opportunity] = []
    for row in frame.to_dict(orient="records"):
        days_left = row.get("days_left", "")
        if days_left == "":
            parsed_days = None
        else:
            try:
                parsed_days = int(float(days_left))
            except Exception:
                parsed_days = None
        items.append(
            Opportunity(
                type=str(row.get("type", "") or ""),
                title=str(row.get("title", "") or ""),
                institution=str(row.get("institution", "") or ""),
                department=str(row.get("department", "") or ""),
                location=str(row.get("location", "") or ""),
                country=str(row.get("country", "") or ""),
                salary=str(row.get("salary", "") or ""),
                posted_date=str(row.get("posted_date", "") or ""),
                application_deadline=str(row.get("application_deadline", "") or ""),
                deadline_status=str(row.get("deadline_status", "") or ""),
                days_left=parsed_days,
                url=str(row.get("url", "") or ""),
                source_site=str(row.get("source_site", "") or ""),
                summary=str(row.get("summary", "") or ""),
                eligibility=str(row.get("eligibility", "") or ""),
                source_key=str(row.get("source_key", "") or ""),
                status=str(row.get("status", "") or ""),
                match_score=float(row.get("match_score", 0) or 0),
                match_reason=str(row.get("match_reason", "") or ""),
                matched_keywords=str(row.get("matched_keywords", "") or ""),
            )
        )
    return items


def _record_to_opportunity(row: dict[str, Any]) -> Opportunity:
    days_left = row.get("days_left", "")
    if days_left in {"", None}:
        parsed_days = None
    else:
        try:
            parsed_days = int(days_left)
        except Exception:
            parsed_days = None
    return Opportunity(
        type=str(row.get("type", "") or ""),
        title=str(row.get("title", "") or ""),
        institution=str(row.get("institution", "") or ""),
        department=str(row.get("department", "") or ""),
        location=str(row.get("location", "") or ""),
        country=str(row.get("country", "") or ""),
        salary=str(row.get("salary", "") or ""),
        posted_date=str(row.get("posted_date", "") or ""),
        application_deadline=str(row.get("application_deadline", "") or ""),
        deadline_status=str(row.get("deadline_status", "") or ""),
        days_left=parsed_days,
        url=str(row.get("url", "") or ""),
        source_site=str(row.get("source_site", "") or ""),
        summary=str(row.get("summary", "") or ""),
        eligibility=str(row.get("eligibility", "") or ""),
        source_key=str(row.get("source_key", "") or ""),
        status=str(row.get("status", "") or ""),
        note=str(row.get("note", "") or ""),
        match_score=float(row.get("match_score", 0) or 0),
        match_reason=str(row.get("match_reason", "") or ""),
        matched_keywords=str(row.get("matched_keywords", "") or ""),
    )

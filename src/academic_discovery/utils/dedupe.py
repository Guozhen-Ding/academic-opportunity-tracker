from __future__ import annotations

import re
from difflib import SequenceMatcher

from academic_discovery.models import Opportunity


AGGREGATOR_SITES = {
    "jobs.ac.uk",
    "www.jobs.ac.uk",
    "academicpositions.com",
    "www.academicpositions.com",
    "euraxess.ec.europa.eu",
}


GENERIC_TITLES = {
    "research associate",
    "research fellow",
    "research assistant",
    "lecturer",
    "professor",
    "scientist",
    "engineer",
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _normalize_title(value: str) -> str:
    return _normalize_text(value)


def _normalize_institution(value: str) -> str:
    raw = value.lower()
    for splitter in [" - ", " / ", " | "]:
        if splitter in raw:
            raw = raw.split(splitter, 1)[0].strip()
            break
    normalized = _normalize_text(raw)
    for splitter in [" department ", " school ", " faculty ", " college ", " laboratory ", " institute "]:
        if splitter in normalized:
            normalized = normalized.split(splitter, 1)[0].strip()
    return normalized


SOURCE_KEY_RANKS = {
    "ukri_epsrc_fellowships": 7,
    "imperial_fellowships": 7,
    "royal_society_grants": 6,
    "leverhulme_listings": 6,
    "imperial_jobs": 6,
    "oxford_jobs": 6,
    "cambridge_jobs": 6,
    "ukri_opportunities": 4,
    "jobs_ac_uk": 2,
    "generic_": 1,
}


def _source_rank(item: Opportunity) -> int:
    source_key = (item.source_key or "").strip().lower()
    for prefix, rank in SOURCE_KEY_RANKS.items():
        if source_key.startswith(prefix):
            return rank
    normalized_site = item.source_site.strip().lower()
    if normalized_site in AGGREGATOR_SITES:
        return 1
    return 3


def _url_quality(item: Opportunity) -> int:
    url = (item.url or "").lower()
    score = 0
    if "/description/" in url or "/job/" in url or "/opportunity/" in url or "/vacancies/" in url:
        score += 2
    if "search?" in url or "filter_" in url or "search-jobs" in url:
        score -= 1
    return score


def _completeness(item: Opportunity) -> int:
    score = 0
    if item.application_deadline:
        score += 2
    if item.salary:
        score += 1
    if item.posted_date:
        score += 1
    if item.summary:
        score += min(len(item.summary.strip()) // 120, 4)
    if item.eligibility:
        score += min(len(item.eligibility.strip()) // 120, 3)
    if item.department:
        score += 1
    return score


def _should_merge(existing: Opportunity, item: Opportunity) -> bool:
    if existing.type != item.type:
        return False

    title_existing = _normalize_title(existing.title)
    title_item = _normalize_title(item.title)
    if not title_existing or not title_item:
        return False

    title_similarity = SequenceMatcher(None, title_existing, title_item).ratio()
    institution_existing = _normalize_institution(existing.institution)
    institution_item = _normalize_institution(item.institution)
    institution_similarity = SequenceMatcher(None, institution_existing, institution_item).ratio() if institution_existing and institution_item else 0.0

    if title_existing == title_item and institution_existing and institution_existing == institution_item:
        return True

    if title_similarity >= 0.96 and institution_similarity >= 0.82:
        return True

    # Allow slightly fuzzier matching for direct-site vs aggregator duplicates,
    # but avoid collapsing generic titles across different institutions.
    if title_similarity >= 0.93 and institution_similarity >= 0.9 and title_item not in GENERIC_TITLES:
        return True

    return False


def _merge_records(existing: Opportunity, item: Opportunity) -> Opportunity:
    preferred, secondary = (existing, item)
    preferred_key = (_source_rank(existing), _url_quality(existing), _completeness(existing))
    challenger_key = (_source_rank(item), _url_quality(item), _completeness(item))
    if challenger_key > preferred_key:
        preferred, secondary = item, existing

    merged = Opportunity(**preferred.__dict__)

    for field in [
        "institution",
        "department",
        "location",
        "country",
        "salary",
        "posted_date",
        "application_deadline",
        "deadline_status",
        "days_left",
        "url",
        "source_site",
        "summary",
        "eligibility",
        "source_key",
        "status",
        "match_reason",
        "matched_keywords",
    ]:
        preferred_value = getattr(merged, field)
        secondary_value = getattr(secondary, field)
        if (preferred_value is None or str(preferred_value).strip() == "") and secondary_value not in {None, ""}:
            setattr(merged, field, secondary_value)

    merged.match_score = max(existing.match_score, item.match_score)
    return merged


def deduplicate(opportunities: list[Opportunity]) -> list[Opportunity]:
    unique: list[Opportunity] = []
    seen_urls: set[str] = set()

    for item in opportunities:
        url_key = item.url.strip().lower()
        if url_key and url_key in seen_urls:
            continue

        duplicate = False
        for index, existing in enumerate(unique):
            if _should_merge(existing, item):
                unique[index] = _merge_records(existing, item)
                duplicate = True
                break

        if duplicate:
            continue

        unique.append(item)
        if url_key:
            seen_urls.add(url_key)

    return unique

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import StaticListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class KULeuvenJobsFetcher(StaticListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 80) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        return self._collect_via_api()

    def _collect_via_api(self) -> list[dict[str, str]]:
        api_url = "https://icts-p-fii-toep-component-filter2.cloud.icts.kuleuven.be/api/projects/Jobsite_academic/search?lang=en"
        payload = {"_locale": "en", "environment": "production"}
        try:
            response = self.session.post(api_url, json=payload, timeout=self.timeout, headers={"User-Agent": self.user_agent})
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []

        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for hit in data.get("hits", []):
            source = hit.get("_source", {})
            posting = source.get("posting", {})
            title = normalize_whitespace(posting.get("title", ""))
            if not title or not _is_relevant_title(title):
                continue
            job_id = str(source.get("id", "") or "").strip()
            if not job_id:
                continue
            url = f"https://www.kuleuven.be/personeel/jobsite/jobs/{job_id}?lang=en"
            if url in seen:
                continue
            seen.add(url)
            apply_before = str(source.get("applyBefore", "") or "").strip()
            apply_text = ""
            if apply_before and len(apply_before) == 8:
                try:
                    apply_text = datetime.strptime(apply_before, "%Y%m%d").date().isoformat()
                except ValueError:
                    apply_text = ""
            items.append(
                {
                    "url": url,
                    "title": title,
                    "listing_text": normalize_whitespace(
                        " ".join(
                            filter(
                                None,
                                [
                                    posting.get("teaser", ""),
                                    source.get("orgUnitDescription", ""),
                                    source.get("city", ""),
                                    f"Application deadline: {apply_text}" if apply_text else "",
                                ],
                            )
                        )
                    ),
                }
            )
            if len(items) >= self.max_results:
                break
        return items

    def extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = _clean_title(normalize_whitespace(_first_text(soup, ["h1", "title"])) or item.get("title", ""))
        if not title:
            return None
        deadline = extract_deadline_info(item.get("listing_text", "") or text)
        summary_source = _section_text(text, ["Offer", "Job description", "Project"])
        return Opportunity(
            type=_infer_type(title, text),
            title=title,
            institution="KU Leuven",
            department=_extract_label(text, ["Department", "Faculty", "Research group"])[:180],
            location=(_extract_label(text, ["Location"]) or "Leuven")[:140],
            country="Belgium",
            salary=_extract_label(text, ["Working Conditions", "Offer"])[:140],
            posted_date=_extract_label(text, ["Last modified", "Published on"])[:140],
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=" ".join(sentence_chunks(summary_source or text)[:6])[:1600],
            eligibility=_section_text(text, ["Profile", "Requirements", "Interested?"])[:800],
            match_score=0.0,
            match_reason="",
        )


def _looks_like_detail(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("kuleuven.be") and "/jobsite/jobs/" in parsed.path


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return normalize_whitespace(node.get_text(" ", strip=True))
    return ""


def _extract_label(text: str, labels: list[str]) -> str:
    lower = text.lower()
    stops = ["offer", "profile", "interested", "apply until", "location", "department", "faculty", "reference"]
    for label in labels:
        idx = lower.find(label.lower())
        if idx < 0:
            continue
        fragment = text[idx + len(label): idx + len(label) + 220].strip(" .,:;-")
        cutoff = len(fragment)
        for stop in stops:
            if stop == label.lower():
                continue
            pos = fragment.lower().find(stop)
            if pos > 0:
                cutoff = min(cutoff, pos)
        return fragment[:cutoff].strip(" .,:;-")
    return ""


def _section_text(text: str, headings: list[str]) -> str:
    lower = text.lower()
    for heading in headings:
        idx = lower.find(heading.lower())
        if idx < 0:
            continue
        section = text[idx + len(heading):]
        for stop in ["Interested?", "Selection timeline", "Apply for this position", "Working Conditions", "Offer", "Profile"]:
            pos = section.lower().find(stop.lower())
            if pos > 120:
                section = section[:pos]
                break
        return normalize_whitespace(section)
    return ""


def _infer_type(title: str, text: str) -> str:
    haystack = f"{title} {text}".lower()
    if any(marker in haystack for marker in ["phd", "doctoral", "fellowship", "scholarship"]):
        return "fellowship"
    return "job"


def _is_relevant_title(title: str) -> bool:
    lower = title.lower()
    include = ["research", "postdoc", "postdoctoral", "fellow", "professor", "lecturer", "assistant professor", "research associate", "phd"]
    exclude = ["medicine", "clinical", "nurse", "lab technician", "administrative", "manager"]
    return any(marker in lower for marker in include) and not any(marker in lower for marker in exclude)


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"^KU Leuven Vacancies\s*\|\s*", "", title, flags=re.I).strip()
    return cleaned

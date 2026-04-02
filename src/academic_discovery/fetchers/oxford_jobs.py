from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class OxfordJobsFetcher(BaseFetcher):
    def __init__(self, base_url: str, max_results: int = 40) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def fetch(self) -> list[Opportunity]:
        soup = self.soup(self.base_url)
        items = self._collect_items(soup)
        opportunities: list[Opportunity] = []
        for item in items:
            try:
                detail_soup = self.soup(item["url"])
            except Exception:
                continue
            opportunity = self._extract_detail(item, detail_soup)
            if opportunity:
                opportunities.append(opportunity)
        return opportunities

    def _collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href*='/jobs/job-detail/']"):
            href = normalize_whitespace(anchor.get("href", ""))
            href = re.sub(r"\s+", "", href)
            url = urljoin(self.base_url, href)
            if url in seen:
                continue
            seen.add(url)
            text = normalize_whitespace(anchor.get_text(" ", strip=True))
            title = re.sub(r"\s+Closing date:.*$", "", text, flags=re.IGNORECASE).strip()
            deadline_text_match = re.search(r"Closing date:\s*(.+?)(?:\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}|$)", text, flags=re.IGNORECASE)
            items.append(
                {
                    "url": url,
                    "title": title or text,
                    "listing_text": text,
                    "closing_date": deadline_text_match.group(1).strip() if deadline_text_match else "",
                }
            )
            if len(items) >= self.max_results:
                break
        return items

    def _extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = _infer_title(text) or item.get("title", "")
        if not title:
            return None
        closing_date = item.get("closing_date", "")
        deadline = extract_deadline_info(f"Closing date: {closing_date}" if closing_date else text)
        body = _body_text(text)
        summary = " ".join(sentence_chunks(body)[:6])[:1600]
        eligibility = _extract_eligibility(body)
        return Opportunity(
            type=_infer_type(title),
            title=title,
            institution="University of Oxford",
            department="Department of Engineering Science",
            location="Oxford",
            country="United Kingdom",
            salary=_extract_between(text, "Salary", "Closing date")[:140],
            posted_date=_extract_between(text, "Date published", "Closing date")[:140],
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=summary,
            eligibility=eligibility[:800],
            match_score=0.0,
            match_reason="",
        )


def _infer_title(text: str) -> str:
    match = re.search(r"ENGINEERING SCIENCE Careers (.*?) Salary", text, flags=re.IGNORECASE)
    if match:
        return normalize_whitespace(match.group(1))
    match = re.search(r"Current vacancies Job Detail ENGINEERING SCIENCE Careers (.*?) Salary", text, flags=re.IGNORECASE)
    if match:
        return normalize_whitespace(match.group(1))
    return ""


def _body_text(text: str) -> str:
    lower = text.lower()
    start = lower.find("description")
    if start >= 0:
        text = text[start + len("description"):].strip()
    for marker in ["To apply", "Further particulars", "Contact", "Share on"]:
        idx = text.lower().find(marker.lower())
        if idx > 200:
            text = text[:idx]
    return text


def _extract_eligibility(text: str) -> str:
    lower = text.lower()
    for marker in ["you should hold", "you will have", "essential", "selection criteria", "applicants will"]:
        idx = lower.find(marker)
        if idx >= 0:
            return text[idx:idx + 800].strip()
    return ""


def _extract_between(text: str, start_label: str, end_label: str) -> str:
    lower = text.lower()
    start = lower.find(start_label.lower())
    end = lower.find(end_label.lower(), start + 1)
    if start < 0 or end < 0 or end <= start:
        return ""
    return text[start + len(start_label):end].strip(" .,:;")


def _infer_type(title: str) -> str:
    lower = title.lower()
    if any(marker in lower for marker in ["studentship", "phd", "fellowship"]):
        return "fellowship"
    return "job"

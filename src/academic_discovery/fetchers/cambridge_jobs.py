from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import StaticListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class CambridgeJobsFetcher(StaticListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 80) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        return self._collect_items(soup)

    def _collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()

        for row in soup.select("tr.views-row, tr.odd, tr.even"):
            cells = row.select("td")
            if len(cells) < 7:
                continue
            title_anchor = cells[0].select_one("a[href]")
            if not title_anchor:
                continue
            href = urljoin(self.base_url, title_anchor["href"])
            if not _looks_like_cambridge_job_url(href) or href in seen:
                continue
            seen.add(href)
            items.append(
                {
                    "url": href,
                    "title": normalize_whitespace(title_anchor.get_text(" ", strip=True)),
                    "department": normalize_whitespace(cells[1].get_text(" ", strip=True)),
                    "salary": normalize_whitespace(cells[2].get_text(" ", strip=True)),
                    "category": normalize_whitespace(cells[3].get_text(" ", strip=True)),
                    "posted_date": normalize_whitespace(cells[4].get_text(" ", strip=True)),
                    "closing_date": normalize_whitespace(cells[5].get_text(" ", strip=True)),
                    "reference": normalize_whitespace(cells[6].get_text(" ", strip=True)),
                }
            )

        if not items:
            for anchor in soup.select("a[href]"):
                href = urljoin(self.base_url, anchor.get("href", ""))
                if not _looks_like_cambridge_job_url(href) or href in seen:
                    continue
                seen.add(href)
                items.append(
                    {
                        "url": href,
                        "title": normalize_whitespace(anchor.get_text(" ", strip=True)),
                        "department": "",
                        "salary": "",
                        "category": "",
                        "posted_date": "",
                        "closing_date": "",
                        "reference": "",
                    }
                )
                if len(items) >= self.max_results:
                    break

        return items[: self.max_results]

    def extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        return self._extract_detail(item, soup)

    def _extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = normalize_whitespace(_first_text(soup, ["h1", "title"])) or item.get("title", "")
        if not title:
            return None

        body_text = _cambridge_body_text(soup, text)
        closing_date = item.get("closing_date", "")
        deadline = extract_deadline_info(f"Closing date: {closing_date}" if closing_date else text)
        posted = item.get("posted_date") or _extract_between(text, "Date published", "Closing date")
        salary = item.get("salary") or _extract_between(text, "Salary", "Reference") or _extract_between(text, "Salary Scales", "Reference")
        department = item.get("department") or _extract_between(text, "Department/location", "Salary") or _extract_between(text, "Department", "Salary")
        category = item.get("category") or _extract_between(text, "Category", "Date published")

        summary = " ".join(sentence_chunks(body_text)[:6])[:1600]
        eligibility = _extract_eligibility(body_text)
        if category:
            department = " | ".join([part for part in [department, category] if part])

        return Opportunity(
            type=_infer_type(title, category, summary),
            title=title,
            institution="University of Cambridge",
            department=department[:180],
            location=_extract_location(text)[:140],
            country="United Kingdom",
            salary=salary[:140],
            posted_date=posted[:140],
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


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return normalize_whitespace(node.get_text(" ", strip=True))
    return ""


def _looks_like_cambridge_job_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")
    return bool(re.match(r"^/jobs/[a-z0-9-]+-[a-z]{2}\d{5}$", path))


def _cambridge_body_text(soup: BeautifulSoup, fallback: str) -> str:
    for selector in [".field", "main", "article", ".layout-container"]:
        node = soup.select_one(selector)
        if not node:
            continue
        text = normalize_whitespace(node.get_text(" ", strip=True))
        if len(text) > 300:
            return text
    return fallback


def _extract_between(text: str, start_label: str, end_label: str) -> str:
    lower = text.lower()
    start = lower.find(start_label.lower())
    end = lower.find(end_label.lower(), start + 1)
    if start < 0 or end < 0 or end <= start:
        return ""
    return text[start + len(start_label):end].strip(" .,:;")


def _extract_eligibility(text: str) -> str:
    lower = text.lower()
    for marker in ["applicants should", "you are required to", "candidates who", "essential", "requirements"]:
        index = lower.find(marker)
        if index >= 0:
            return text[index:index + 800].strip()
    return ""


def _extract_location(text: str) -> str:
    for label in ["Department/location", "Location", "based on"]:
        snippet = _extract_between(text, label, "Salary")
        if snippet:
            return snippet
    return "Cambridge"


def _infer_type(title: str, category: str, summary: str) -> str:
    haystack = f"{title} {category} {summary}".lower()
    if any(marker in haystack for marker in ["studentship", "phd", "fellowship", "scholarship"]):
        return "fellowship"
    return "job"

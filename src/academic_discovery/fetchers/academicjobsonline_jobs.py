from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.models import DeadlineInfo
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


DEFAULT_BOARDS = [
    "https://academicjobsonline.org/ajo/Eng/Materials%20Science",
    "https://academicjobsonline.org/ajo/Eng/Mechanical%20Engineering",
    "https://academicjobsonline.org/ajo/Eng/Civil%20Engineering",
    "https://academicjobsonline.org/ajo/Eng/Chemical%20Engineering",
]


class AcademicJobsOnlineFetcher(BaseFetcher):
    def __init__(self, base_url: str, boards: list[str] | None = None, max_results: int = 120) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.boards = boards or DEFAULT_BOARDS
        self.max_results = max_results

    def fetch(self) -> list[Opportunity]:
        items = self._collect_items()
        opportunities: list[Opportunity] = []
        detail_success = 0
        detail_failed = 0
        parser_failures = 0
        self.update_diagnostics(list_count=len(items), fetch_mode="static")
        for item in items:
            try:
                detail_soup = self.soup(item["url"])
                opportunity = self._extract_detail(item, detail_soup)
            except Exception:
                detail_failed += 1
                continue
            if opportunity is None:
                parser_failures += 1
                continue
            detail_success += 1
            opportunities.append(opportunity)
        self.update_diagnostics(detail_success=detail_success, detail_failed=detail_failed, parser_failures=parser_failures)
        return opportunities

    def _collect_items(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for board_url in self.boards:
            try:
                soup = self.soup(board_url)
            except Exception:
                continue
            for anchor in soup.select("a[href*='/ajo/jobs/']"):
                href = anchor.get("href", "")
                url = urljoin(self.base_url + "/", href)
                if not _looks_like_detail(url) or url in seen:
                    continue
                title = normalize_whitespace(anchor.get_text(" ", strip=True))
                if title and not _is_relevant_title(title):
                    continue
                seen.add(url)
                items.append(
                    {
                        "url": url,
                        "board_url": board_url,
                        "title": title,
                        "listing_text": _listing_context(anchor),
                    }
                )
                if len(items) >= self.max_results:
                    return items
        return items

    def _extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = _extract_labeled_value(text, "Position Title") or normalize_whitespace(_first_text(soup, ["h1", "title"])) or item.get("title", "")
        if not title or title.lower().startswith("engineering /"):
            return None
        deadline = _ajo_deadline(_extract_labeled_value(text, "Appl Deadline"))
        location = _extract_labeled_value(text, "Position Location")
        summary_source = _section_text(text, ["Position Description", "Description"])
        institution = normalize_whitespace(_first_text(soup, ["h2", "h1 + div", "title"])) or "AcademicJobsOnline"
        return Opportunity(
            type=_infer_type(title, text),
            title=title,
            institution=institution[:180],
            department=_extract_labeled_value(text, "Subject Areas")[:180],
            location=location[:140],
            country=_extract_country(location)[:140],
            salary="",
            posted_date=_extract_posted_date(text)[:140],
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=" ".join(sentence_chunks(summary_source or text)[:6])[:1600],
            eligibility=_section_text(text, ["Qualifications", "Required Qualifications", "Application Instructions"])[:800],
            match_score=0.0,
            match_reason="",
        )


def _looks_like_detail(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("academicjobsonline.org") and "/ajo/jobs/" in parsed.path


def _listing_context(anchor: BeautifulSoup) -> str:
    node = anchor
    best = ""
    for _ in range(6):
        node = node.parent
        if not getattr(node, "get_text", None):
            break
        text = normalize_whitespace(node.get_text(" ", strip=True))
        if len(text) > len(best):
            best = text
        if len(text) > 240:
            break
    return best


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return normalize_whitespace(node.get_text(" ", strip=True))
    return ""


def _extract_labeled_value(text: str, label: str) -> str:
    lower = text.lower()
    idx = lower.find(label.lower())
    if idx < 0:
        return ""
    fragment = text[idx + len(label): idx + len(label) + 220].strip(" .,:;-")
    for stop in ["Position Type", "Position Location", "Subject Areas", "Appl Deadline", "Position Description", "Qualifications", "Application Instructions"]:
        if stop.lower() == label.lower():
            continue
        pos = fragment.lower().find(stop.lower())
        if pos > 0:
            fragment = fragment[:pos]
            break
    return fragment.strip(" .,:;-")


def _section_text(text: str, headings: list[str]) -> str:
    lower = text.lower()
    for heading in headings:
        idx = lower.find(heading.lower())
        if idx < 0:
            continue
        section = text[idx + len(heading):]
        for stop in ["Qualifications", "Application Instructions", "Equal Employment Opportunity Statement"]:
            pos = section.lower().find(stop.lower())
            if pos > 120:
                section = section[:pos]
                break
        return normalize_whitespace(section)
    return ""


def _extract_posted_date(text: str) -> str:
    match = re.search(r"posted\s+(\d{4}/\d{2}/\d{2})", text, re.I)
    return match.group(1) if match else ""


def _extract_country(location: str) -> str:
    if "," in location:
        return normalize_whitespace(location.split(",")[-1])
    return ""


def _infer_type(title: str, text: str) -> str:
    haystack = f"{title} {text}".lower()
    if any(marker in haystack for marker in ["fellowship", "phd", "postdoctoral", "postdoc"]):
        return "fellowship"
    return "job"


def _is_relevant_title(title: str) -> bool:
    lower = title.lower()
    include = ["assistant professor", "associate professor", "professor", "chair", "postdoctoral", "postdoc", "research fellow", "research associate", "fellowship"]
    exclude = ["adjunct", "visiting instructor", "lecturer pool"]
    return any(marker in lower for marker in include) and not any(marker in lower for marker in exclude)


def _ajo_deadline(value: str) -> DeadlineInfo:
    cleaned = normalize_whitespace(value)
    listed_until = re.search(r"listed until\s+(\d{4}/\d{2}/\d{2})", cleaned, re.I)
    if listed_until:
        parsed = date_parser.parse(listed_until.group(1), fuzzy=True).date()
        return DeadlineInfo(label="fixed deadline", date_value=parsed, days_left=(parsed - date.today()).days)
    return extract_deadline_info(f"Application deadline: {cleaned}")

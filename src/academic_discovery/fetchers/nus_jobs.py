from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import StaticListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class NUSJobsFetcher(StaticListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 80) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href*='/job/'], a[href*='/NUS/job/']"):
            href = anchor.get("href", "")
            url = urljoin(self.base_url, href)
            if not _looks_like_detail(url) or url in seen:
                continue
            title = normalize_whitespace(anchor.get_text(" ", strip=True))
            if not title or not _is_relevant_title(title):
                continue
            seen.add(url)
            items.append({"url": url, "title": title, "listing_text": _listing_context(anchor)})
            if len(items) >= self.max_results:
                break
        return items

    def extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = normalize_whitespace(_first_text(soup, ["h1", "title"])) or item.get("title", "")
        if not title:
            return None
        deadline = extract_deadline_info(text)
        summary_source = _section_text(text, ["Job Description", "Description", "About The Role"])
        return Opportunity(
            type=_infer_type(title, text),
            title=title,
            institution="National University of Singapore",
            department=_extract_label(text, ["Department", "School", "Faculty", "Hiring Department"])[:180],
            location=(_extract_label(text, ["Location"]) or "Singapore")[:140],
            country="Singapore",
            salary=_extract_label(text, ["Salary", "Compensation"])[:140],
            posted_date=_extract_label(text, ["Posting Date", "Date Posted", "Job Posting Date"])[:140],
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=" ".join(sentence_chunks(summary_source or text)[:6])[:1600],
            eligibility=_section_text(text, ["Qualifications", "Requirements", "Job Requirements"])[:800],
            match_score=0.0,
            match_reason="",
        )


def _looks_like_detail(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("nus.edu.sg") and "/job/" in parsed.path.lower()


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
        if len(text) > 220:
            break
    return best


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return normalize_whitespace(node.get_text(" ", strip=True))
    return ""


def _extract_label(text: str, labels: list[str]) -> str:
    lower = text.lower()
    stops = ["job description", "qualifications", "requirements", "more information", "location", "department", "posting date"]
    for label in labels:
        idx = lower.find(label.lower())
        if idx < 0:
            continue
        fragment = text[idx + len(label): idx + len(label) + 180].strip(" .,:;-")
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
        for stop in ["Qualifications", "Requirements", "More Information", "Department", "Location"]:
            pos = section.lower().find(stop.lower())
            if pos > 120:
                section = section[:pos]
                break
        return normalize_whitespace(section)
    return ""


def _infer_type(title: str, text: str) -> str:
    haystack = f"{title} {text}".lower()
    if any(marker in haystack for marker in ["fellowship", "postdoctoral", "postdoctoral fellow", "phd"]):
        return "fellowship"
    return "job"


def _is_relevant_title(title: str) -> bool:
    lower = title.lower()
    include = ["research", "postdoc", "postdoctoral", "fellow", "professor", "lecturer", "scientist", "engineer", "phd"]
    exclude = ["manager", "administrator", "executive", "assistant (admin", "operations", "finance"]
    return any(marker in lower for marker in include) and not any(marker in lower for marker in exclude)

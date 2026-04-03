from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import StaticListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class EuraxessJobsFetcher(StaticListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 80) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.max_results = max_results

    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href*='/jobs/']"):
            href = anchor.get("href", "")
            url = urljoin(self.base_url + "/", href)
            if not _looks_like_detail(url) or url in seen:
                continue
            title = normalize_whitespace(anchor.get_text(" ", strip=True))
            if not title:
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
        listing_deadline = extract_deadline_info(item.get("listing_text", "")) if item.get("listing_text") else deadline
        summary_source = _section_text(text, "Offer Description")
        country = _extract_label(text, ["Country"]) or _country_from_listing(item.get("listing_text", ""))
        location = _extract_label(text, ["Work Location(s)", "Country"]) or country
        return Opportunity(
            type=_infer_type(title, text),
            title=title,
            institution=_extract_label(text, ["Organisation/Company"])[:180],
            department=_extract_label(text, ["Department"])[:180],
            location=location[:140],
            country=country[:140],
            salary=_extract_label(text, ["Gross monthly salary", "Salary"])[:140],
            posted_date=_extract_label(text, ["Posted on"])[:140],
            application_deadline=(listing_deadline.date_value or deadline.date_value).isoformat() if (listing_deadline.date_value or deadline.date_value) else "",
            deadline_status=listing_deadline.label if listing_deadline.date_value else deadline.label,
            days_left=listing_deadline.days_left if listing_deadline.date_value else deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=" ".join(sentence_chunks(summary_source or text)[:6])[:1600],
            eligibility=_section_text(text, "Requirements")[:800],
            match_score=0.0,
            match_reason="",
        )


def _looks_like_detail(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("euraxess.ec.europa.eu") and bool(re.match(r"^/jobs/\d+", parsed.path))


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


def _extract_label(text: str, labels: list[str]) -> str:
    lower = text.lower()
    stop_words = [
        "department", "research field", "researcher profile", "positions", "country",
        "application deadline", "type of contract", "job status", "hours per week",
        "offer description", "where to apply", "requirements", "additional information",
        "work location", "contact", "posted on",
    ]
    for label in labels:
        idx = lower.find(label.lower())
        if idx < 0:
            continue
        fragment = text[idx + len(label): idx + len(label) + 220].strip(" .,:;-")
        cutoff = len(fragment)
        for stop in stop_words:
            if stop.lower() == label.lower():
                continue
            pos = fragment.lower().find(stop.lower())
            if pos > 0:
                cutoff = min(cutoff, pos)
        return fragment[:cutoff].strip(" .,:;-")
    return ""


def _section_text(text: str, heading: str) -> str:
    lower = text.lower()
    start = lower.find(heading.lower())
    if start < 0:
        return ""
    section = text[start + len(heading):]
    for stop in ["Where to apply", "Requirements", "Additional Information", "Work Location(s)", "Contact"]:
        idx = section.lower().find(stop.lower())
        if idx > 120:
            section = section[:idx]
            break
    return normalize_whitespace(section)


def _country_from_listing(text: str) -> str:
    for part in [segment.strip() for segment in (text or "").split(" * ") if segment.strip()]:
        if len(part.split()) <= 4 and "Posted on" not in part and part.upper() != part:
            return part
    return ""


def _infer_type(title: str, text: str) -> str:
    haystack = f"{title} {text}".lower()
    if any(marker in haystack for marker in ["fellowship", "phd", "studentship", "scholarship"]):
        return "fellowship"
    return "job"

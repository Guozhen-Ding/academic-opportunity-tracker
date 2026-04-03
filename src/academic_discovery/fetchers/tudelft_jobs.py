from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import StaticListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.models import DeadlineInfo
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class TUDelftJobsFetcher(StaticListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 80, max_pages: int = 5) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results
        self.max_pages = max_pages

    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        page_urls = [self.base_url]
        for anchor in soup.select("a[href*='/go/All-jobs/']"):
            href = urljoin(self.base_url, anchor.get("href", ""))
            if href not in page_urls:
                page_urls.append(href)
        for page_url in page_urls[: self.max_pages]:
            page_soup = soup if page_url == self.base_url else self.soup(page_url)
            for anchor in page_soup.select("a[href*='/job/']"):
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
                    return items
        return items

    def extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = normalize_whitespace(_first_text(soup, ["h1", "title"])) or item.get("title", "")
        if not title:
            return None
        listing_deadline = _deadline_from_listing(item.get("listing_text", ""))
        deadline = listing_deadline if listing_deadline.date_value else extract_deadline_info(text)
        summary_source = _section_text(text, ["Job description", "The position"])
        return Opportunity(
            type=_infer_type(title, text),
            title=title,
            institution="TU Delft",
            department=_extract_label(text, ["Faculty", "Department"])[:180],
            location=(_extract_label(text, ["Location"]) or "Delft")[:140],
            country="Netherlands",
            salary=_extract_label(text, ["Salary", "Conditions of employment"])[:140],
            posted_date=_extract_label(text, ["Published"])[:140],
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=" ".join(sentence_chunks(summary_source or text)[:6])[:1600],
            eligibility=_section_text(text, ["Job requirements", "Requirements", "You have"])[:800],
            match_score=0.0,
            match_reason="",
        )


def _looks_like_detail(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("tudelft.nl") and "/job/" in parsed.path


def _listing_context(anchor: BeautifulSoup) -> str:
    node = anchor
    best = ""
    best_len = 0
    for depth in range(6):
        node = node.parent
        if not getattr(node, "get_text", None):
            break
        text = normalize_whitespace(node.get_text(" ", strip=True))
        if depth >= 2 and len(text) > best_len and len(text) < 350:
            best = text
            best_len = len(text)
        if depth >= 2 and len(text) > 240:
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
    for label in labels:
        idx = lower.find(label.lower())
        if idx < 0:
            continue
        fragment = text[idx + len(label): idx + len(label) + 220].strip(" .,:;-")
        for stop in ["conditions of employment", "job requirements", "job description", "application procedure", "faculty", "department", "location"]:
            if stop == label.lower():
                continue
            pos = fragment.lower().find(stop)
            if pos > 0:
                fragment = fragment[:pos]
                break
        for split_marker in [" published ", " closing date ", " apply before "]:
            pos = fragment.lower().find(split_marker)
            if pos > 0:
                fragment = fragment[:pos]
                break
        return fragment.strip(" .,:;-")
    return ""


def _section_text(text: str, headings: list[str]) -> str:
    lower = text.lower()
    for heading in headings:
        idx = lower.find(heading.lower())
        if idx < 0:
            continue
        section = text[idx + len(heading):]
        for stop in ["Job requirements", "Conditions of employment", "Additional information", "Application procedure"]:
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
    include = ["research", "postdoc", "postdoctoral", "fellow", "professor", "lecturer", "assistant professor", "researcher", "phd"]
    exclude = ["technician", "administrative", "manager", "clinical", "biology"]
    return any(marker in lower for marker in include) and not any(marker in lower for marker in exclude)


def _deadline_from_listing(text: str) -> DeadlineInfo:
    fragment = normalize_whitespace(text)
    match = re.search(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s*$", fragment)
    if match:
        return extract_deadline_info(f"Closing date: {match.group(1)}")
    return DeadlineInfo(label="unknown deadline")

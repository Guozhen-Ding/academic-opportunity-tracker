from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class RoyalSocietyGrantsFetcher(BaseFetcher):
    def __init__(self, base_url: str, max_results: int = 60, max_pages: int = 6) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results
        self.max_pages = max_pages

    def fetch(self) -> list[Opportunity]:
        items = self._collect_items()
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

    def _collect_items(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        next_page = 1
        for _ in range(self.max_pages):
            page_url = self.base_url if next_page == 1 else f"{self.base_url}?page={next_page}"
            soup = self.soup(page_url)
            page_added = 0
            for article in soup.select("article"):
                anchor = article.select_one("a[href]")
                if not anchor:
                    continue
                href = urljoin(self.base_url, anchor.get("href", ""))
                parsed = urlparse(href)
                if parsed.path == "/" or "/grants/" not in parsed.path:
                    continue
                if any(blocked in parsed.path for blocked in ["/applications/", "/application-dates/", "/training-networking-opportunities/", "/global-talent-", "/about-grants/", "/contact-details-"]):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                text = normalize_whitespace(article.get_text(" ", strip=True))
                title = normalize_whitespace(anchor.get_text(" ", strip=True))
                items.append({"url": href, "title": title, "listing_text": text})
                page_added += 1
                if len(items) >= self.max_results:
                    return items
            next_button = soup.select_one("button.js-postDisplayPaginationLink[data-value]")
            if not next_button or page_added == 0:
                break
            try:
                next_page = int(next_button.get("data-value", "0"))
            except ValueError:
                break
        return items

    def _extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = normalize_whitespace(_first_text(soup, ["h1", "title"])) or item.get("title", "")
        if not title:
            return None
        deadline = _royal_society_deadline(text, item.get("listing_text", ""))
        body = _body_text(text)
        summary = " ".join(sentence_chunks(body)[:6])[:1600]
        eligibility = _extract_section(body, ["Eligibility", "Who can apply", "Applicants must", "Support for disabled applicants"])[:800]
        return Opportunity(
            type="fellowship",
            title=title,
            institution="The Royal Society",
            department="Grants",
            location="United Kingdom",
            country="United Kingdom",
            salary=_extract_section(body, ["What does the scheme offer?", "Funding available", "Award value"])[:140],
            posted_date="",
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=summary,
            eligibility=eligibility,
            match_score=0.0,
            match_reason="",
        )


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return normalize_whitespace(node.get_text(" ", strip=True))
    return ""


def _body_text(text: str) -> str:
    start_markers = ["About the scheme", "What does the scheme offer?", "Eligibility", "This scheme"]
    start = 0
    lower = text.lower()
    for marker in start_markers:
        idx = lower.find(marker.lower())
        if idx >= 0:
            start = idx
            break
    excerpt = text[start:]
    for marker in ["Application tips", "Application and offer data", "Support for disabled applicants", "Contact"]:
        idx = excerpt.lower().find(marker.lower())
        if idx > 250:
            excerpt = excerpt[:idx]
    return excerpt


def _extract_section(text: str, markers: list[str]) -> str:
    lower = text.lower()
    for marker in markers:
        idx = lower.find(marker.lower())
        if idx >= 0:
            return text[idx:idx + 900].strip()
    return ""


def _royal_society_deadline(text: str, listing_text: str):
    section = _extract_section(text, ["2027", "2026", "Opening date", "Closing date", "Open date", "Close date"])
    return extract_deadline_info(section or listing_text or "")

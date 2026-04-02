from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class UKRIOpportunitiesFetcher(BaseFetcher):
    def __init__(self, base_url: str, max_pages: int = 12, max_results: int = 120) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/") + "/"
        self.max_pages = max_pages
        self.max_results = max_results

    def fetch(self) -> list[Opportunity]:
        items = self._collect_listing_items()
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

    def _collect_listing_items(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = self.base_url if page == 1 else urljoin(self.base_url, f"page/{page}/")
            try:
                soup = self.soup(url)
            except Exception:
                continue
            page_added = 0
            for block in soup.select("div, article, li"):
                text = normalize_whitespace(block.get_text(" ", strip=True))
                if "Opportunity status:" not in text or "Opening date:" not in text or "Closing date:" not in text:
                    continue
                anchor = None
                for candidate in block.select("a[href]"):
                    href = candidate.get("href", "")
                    if "/opportunity/" in href and "/page/" not in href and "filter_order" not in href and not href.rstrip("/").endswith("/opportunity"):
                        anchor = candidate
                        break
                if not anchor:
                    continue
                href = urljoin(self.base_url, anchor.get("href", ""))
                if href in seen:
                    continue
                seen.add(href)
                items.append(
                    {
                        "url": href,
                        "title": normalize_whitespace(anchor.get_text(" ", strip=True)),
                        "listing_text": text,
                    }
                )
                page_added += 1
                if len(items) >= self.max_results:
                    return items
            if page_added == 0:
                break
        return items

    def _extract_detail(self, item: dict[str, str], soup: BeautifulSoup) -> Opportunity | None:
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = normalize_whitespace(_first_text(soup, ["h1", "title"])) or item.get("title", "")
        if not title:
            return None
        deadline = extract_deadline_info(item.get("listing_text", "") or text)
        summary = _extract_summary(text)
        eligibility = _extract_eligibility(text)
        return Opportunity(
            type="fellowship",
            title=title,
            institution="UK Research and Innovation",
            department=_extract_label(text, ["Funders", "Funding type"])[:180],
            location="United Kingdom",
            country="United Kingdom",
            salary=_extract_label(text, ["Award range", "Total fund", "Funding type"])[:140],
            posted_date=_extract_label(text, ["Publication date", "Published"])[:140],
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


def _extract_summary(text: str) -> str:
    start_markers = ["Apply for funding", "Opportunity status", "Funding finder"]
    start = 0
    lower = text.lower()
    for marker in start_markers:
        idx = lower.find(marker.lower())
        if idx >= 0:
            start = idx
            break
    excerpt = text[start:]
    for marker in ["Who can apply", "How to apply", "Supporting documents", "Contact details"]:
        idx = excerpt.lower().find(marker.lower())
        if idx > 250:
            excerpt = excerpt[:idx]
    return " ".join(sentence_chunks(excerpt)[:6])[:1600]


def _extract_eligibility(text: str) -> str:
    for marker in ["Who can apply", "The project lead must", "To apply", "Eligibility"]:
        idx = text.lower().find(marker.lower())
        if idx >= 0:
            return text[idx:idx + 800].strip()
    return ""


def _extract_label(text: str, labels: list[str]) -> str:
    lower = text.lower()
    for label in labels:
        idx = lower.find(label.lower())
        if idx >= 0:
            return text[idx:idx + 180].strip(" .,:;")
    return ""

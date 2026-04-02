from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class LeverhulmeListingsFetcher(BaseFetcher):
    def __init__(self, base_url: str, max_results: int = 20) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def fetch(self) -> list[Opportunity]:
        soup = self.soup(self.base_url)
        links = self._collect_scheme_links(soup)
        opportunities: list[Opportunity] = []
        for link in links:
            try:
                detail_soup = self.soup(link)
            except Exception:
                continue
            opportunity = self._extract_detail(link, detail_soup)
            if opportunity:
                opportunities.append(opportunity)
        return opportunities

    def _collect_scheme_links(self, soup: BeautifulSoup) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        allowed_paths = {
            "/art-scholarship-training-opportunities-under-18s",
            "/art-scholarship-bursaries-undergraduates-and-postgraduates",
            "/early-career-fellowships",
            "/emeritus-fellowships",
            "/leverhulme-doctoral-scholarships",
            "/leverhulme-research-centres",
            "/major-research-fellowships",
            "/philip-leverhulme-prizes",
            "/research-fellowships",
            "/research-leadership-awards",
            "/research-project-grants",
            "/visiting-professorships",
        }
        for anchor in soup.select("a[href]"):
            href = urljoin(self.base_url, anchor.get("href", ""))
            parsed = urlparse(href)
            path = parsed.path.rstrip("/").lower()
            text = normalize_whitespace(anchor.get_text(" ", strip=True))
            if parsed.netloc != urlparse(self.base_url).netloc:
                continue
            if path not in allowed_paths:
                continue
            if not text:
                continue
            if href in seen:
                continue
            seen.add(href)
            candidates.append(href)
            if len(candidates) >= self.max_results:
                break
        return candidates

    def _extract_detail(self, url: str, soup: BeautifulSoup) -> Opportunity | None:
        title = normalize_whitespace(_first_text(soup, ["h1", "title"]))
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        if not title:
            return None

        deadline = _leverhulme_deadline(text)
        body = _body_text(soup, text)
        summary = " ".join(sentence_chunks(body)[:6])[:1600]
        eligibility = _extract_eligibility(body)

        return Opportunity(
            type="fellowship",
            title=title,
            institution="The Leverhulme Trust",
            department="Funding",
            location="United Kingdom",
            country="United Kingdom",
            salary=_extract_label(text, ["value", "award", "funding", "support"])[:140],
            posted_date="",
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=url,
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


def _body_text(soup: BeautifulSoup, fallback: str) -> str:
    for selector in ["main", "article", ".region-content", ".node__content", ".field--name-body"]:
        node = soup.select_one(selector)
        if not node:
            continue
        text = normalize_whitespace(node.get_text(" ", strip=True))
        if len(text) > 250:
            return text
    return fallback


def _extract_eligibility(text: str) -> str:
    lower = text.lower()
    for marker in ["eligibility", "for early career researchers", "can be held at", "applicants should", "who can apply"]:
        idx = lower.find(marker)
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


def _leverhulme_deadline(text: str):
    key_dates = _extract_key_dates_block(text)
    if key_dates:
        return extract_deadline_info(key_dates)
    return extract_deadline_info("")


def _extract_key_dates_block(text: str) -> str:
    match = re.search(r"key dates(.*?)(making an application|contact|keep in touch)", text, flags=re.IGNORECASE)
    if not match:
        return ""
    block = normalize_whitespace(match.group(1))
    if any(marker in block.lower() for marker in ["closes", "closing date", "opens", "opening date"]):
        return block
    return ""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class GenericOpportunityFetcher(BaseFetcher):
    def __init__(self, target: dict) -> None:
        super().__init__()
        self.target = target
        self.base_url = target["url"]
        self.expected_type = target.get("type", "fellowship")
        self.keywords = [item.lower() for item in target.get("keywords", [])]
        self.max_links = int(target.get("max_links", 10))
        self.emit_base_page = bool(target.get("emit_base_page", False))
        self.detail_markers = [item.lower() for item in target.get("detail_markers", [])]

    def fetch(self) -> list[Opportunity]:
        soup = self.soup(self.base_url)
        opportunities: list[Opportunity] = []
        if self.emit_base_page:
            opportunities.extend(self._extract_from_page(soup, self.base_url))

        if self.target.get("crawl_links", True):
            for link in self._candidate_links(soup):
                try:
                    link_soup = self.soup(link)
                except Exception:
                    continue
                opportunities.extend(self._extract_from_page(link_soup, link))
        return opportunities

    def _candidate_links(self, soup: BeautifulSoup) -> list[str]:
        special = self._special_candidate_links(soup)
        if special is not None:
            return special

        base_host = urlparse(self.base_url).netloc
        normalized_base = self.base_url.rstrip("/")
        candidates: list[str] = []
        for anchor in soup.select("a[href]"):
            href = urljoin(self.base_url, anchor["href"]).split("#", 1)[0]
            host = urlparse(href).netloc
            text = normalize_whitespace(anchor.get_text(" ", strip=True)).lower()
            if host != base_host:
                continue
            if href.rstrip("/") == normalized_base:
                continue
            if self._skip_non_detail_link(href, text):
                continue
            if self.keywords and not any(keyword in text or keyword in href.lower() for keyword in self.keywords):
                continue
            if href not in candidates:
                candidates.append(href)
            if len(candidates) >= self.max_links:
                break
        return candidates

    def _special_candidate_links(self, soup: BeautifulSoup) -> list[str] | None:
        parsed = urlparse(self.base_url)
        if "royalsociety.org" in parsed.netloc and "/grants/search/grant-listings/" in parsed.path:
            candidates: list[str] = []
            for article in soup.select("article"):
                anchor = article.select_one("a[href]")
                if not anchor:
                    continue
                href = urljoin(self.base_url, anchor["href"]).split("#", 1)[0]
                text = normalize_whitespace(article.get_text(" ", strip=True)).lower()
                if "/grants/" not in href:
                    continue
                if any(marker in href.lower() for marker in ["/applications/", "/application-dates/", "/training-networking-opportunities/", "/global-talent-", "/contact-details-", "/about-grants/"]):
                    continue
                if not any(marker in text for marker in ["closed", "opening", "opens", "closes", "fellowship", "award", "exchange"]):
                    continue
                if href not in candidates:
                    candidates.append(href)
                if len(candidates) >= self.max_links:
                    break
            return candidates
        return None

    def _extract_from_page(self, soup: BeautifulSoup, page_url: str) -> list[Opportunity]:
        page_text = _visible_text(soup)
        title = self._page_title(soup, page_text)
        if not self._looks_relevant(title, page_text):
            return []
        if self._is_portal_page(title, page_text, page_url):
            return []
        if not self._looks_like_detail_page(title, page_text, page_url):
            return []

        deadline = extract_deadline_info(page_text)
        content_text = _content_text(soup, page_text)
        summary = _extract_summary(content_text)
        eligibility = _extract_eligibility(content_text)

        return [
            Opportunity(
                type=self.expected_type,
                title=title,
                institution=self.target.get("institution", _domain_label(page_url)),
                department=self.target.get("department", ""),
                location=_extract_labeled_text(page_text, ["location", "based in"])[:120],
                country=_extract_labeled_text(page_text, ["country"])[:80],
                salary=_extract_labeled_text(page_text, ["salary", "stipend", "funding"])[:120],
                posted_date=_extract_labeled_text(page_text, ["posted", "published", "date"])[:120],
                application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
                deadline_status=deadline.label,
                days_left=deadline.days_left,
                url=page_url,
                source_site=urlparse(self.base_url).netloc,
                summary=summary,
                eligibility=eligibility[:700],
                match_score=0.0,
                match_reason="",
            )
        ]

    def _page_title(self, soup: BeautifulSoup, page_text: str) -> str:
        for selector in ["h1", "title", "h2"]:
            node = soup.select_one(selector)
            if node:
                title = normalize_whitespace(node.get_text(" ", strip=True))
                if title.lower() not in {"careers", "current vacancies", "jobs", "vacancies", "job detail", "description"}:
                    return title
        inferred = _infer_embedded_title(page_text)
        if inferred:
            return inferred
        return self.target.get("name", "Untitled opportunity")

    def _looks_relevant(self, title: str, page_text: str) -> bool:
        haystack = f"{title} {page_text}".lower()
        positive_markers = self.keywords or ["fellowship", "job", "vacancy", "postdoctoral", "studentship"]
        return any(marker in haystack for marker in positive_markers)

    def _looks_like_detail_page(self, title: str, page_text: str, page_url: str) -> bool:
        haystack = f"{title} {page_url} {page_text[:2500]}".lower()
        detail_markers = self.detail_markers or [
            "apply",
            "application",
            "closing date",
            "deadline",
            "closes",
            "job ref",
            "salary",
            "hours",
            "contract type",
            "posted on",
            "placed on",
            "requirements",
            "person specification",
            "eligibility",
        ]
        return any(marker in haystack for marker in detail_markers)

    def _is_portal_page(self, title: str, page_text: str, page_url: str) -> bool:
        haystack = f"{title} {page_url}".lower()
        portal_markers = [
            "home",
            "department of",
            "school of",
            "faculty of",
            "engineering",
            "employment",
            "jobs",
            "vacancies",
            "opportunities",
        ]
        generic_titles = [
            "jobs",
            "vacancies",
            "employment",
            "engineering",
            "department of engineering",
            "current vacancies",
            "careers",
            "job detail",
            "description",
        ]
        title_lower = title.lower().strip()
        if title_lower in generic_titles:
            return True
        many_links = page_text.lower().count("apply") < 2 and len(page_text) > 2500
        portalish = any(marker in haystack for marker in portal_markers)
        return portalish and many_links and not self._looks_like_detail_page(title, page_text, page_url)

    def _skip_non_detail_link(self, href: str, text: str) -> bool:
        lower_href = href.lower()
        lower_text = text.lower()
        blocked = [
            "/news",
            "/events",
            "/study",
            "/about",
            "/contact",
            "/research",
            "/people",
            "/departments",
            "/faculties",
            "/engineering/",
        ]
        if any(marker in lower_href for marker in blocked):
            return True
        if len(lower_text) < 4:
            return True
        return False


def _extract_labeled_text(text: str, labels: list[str]) -> str:
    lower = text.lower()
    for label in labels:
        index = lower.find(label.lower())
        if index >= 0:
            return text[index:index + 140].strip(" .,:;")
    return ""


def _domain_label(url: str) -> str:
    host = urlparse(url).netloc
    parts = [part for part in host.split(".") if part and part != "www"]
    return parts[0].replace("-", " ").title() if parts else host


def _content_text(soup: BeautifulSoup, page_text: str) -> str:
    selectors = [
        ".field-item",
        "main",
        "article",
        ".content",
        ".content-area",
        ".region-content",
        ".content__main",
        ".section-content",
    ]
    candidates: list[str] = []
    for selector in selectors:
        for node in soup.select(selector)[:3]:
            text = normalize_whitespace(node.get_text(" ", strip=True))
            if len(text) > 200:
                candidates.append(text)
    source = max(candidates, key=len) if candidates else page_text
    return _body_excerpt(source)


def _extract_summary(text: str) -> str:
    return " ".join(sentence_chunks(text)[:6])[:1500]


def _extract_eligibility(text: str) -> str:
    return _extract_labeled_text(
        text,
        [
            "eligibility",
            "who can apply",
            "applicants should",
            "requirements",
            "person specification",
            "what we are looking for",
            "candidate profile",
        ],
    )[:700]


def _body_excerpt(text: str) -> str:
    cleaned = normalize_whitespace(text)
    lower = cleaned.lower()

    start_markers = [
        "applications are invited",
        "about the scheme",
        "about the role",
        "for early career researchers",
        "for well-established",
        "we are dedicated to supporting",
        "the scheme",
        "the successful applicant",
    ]
    start = 0
    for marker in start_markers:
        idx = lower.find(marker)
        if idx >= 0:
            start = idx
            break

    excerpt = cleaned[start:]
    excerpt_lower = excerpt.lower()
    end_markers = [
        "how to apply",
        "apply now",
        "application and assessment process",
        "contact details",
        "further information",
        "share this page",
        "latest news",
        "related links",
    ]
    end = len(excerpt)
    for marker in end_markers:
        idx = excerpt_lower.find(marker)
        if idx > 250:
            end = min(end, idx)
    return excerpt[:end].strip()


def _visible_text(soup: BeautifulSoup) -> str:
    cleaned = BeautifulSoup(str(soup), "html.parser")
    for node in cleaned(["script", "style", "noscript", "svg"]):
        node.decompose()
    return normalize_whitespace(cleaned.get_text(" ", strip=True))


def _infer_embedded_title(page_text: str) -> str:
    patterns = [
        r"careers\s+(.*?)\s+salary\b",
        r"careers\s+(.*?)\s+closing date\b",
        r"careers\s+(.*?)\s+grade\b",
        r"job details\s+(.*?)\s+salary\b",
        r"job details\s+(.*?)\s+closing date\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            title = normalize_whitespace(match.group(1))
            if 8 <= len(title) <= 180:
                return title
    return ""

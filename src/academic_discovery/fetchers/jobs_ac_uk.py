from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class JobsAcUkFetcher(BaseFetcher):
    def __init__(self, base_url: str, queries: list[str], max_pages: int = 1) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/") + "/"
        self.queries = queries
        self.max_pages = max_pages

    def fetch(self) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for query in self.queries:
            for page in range(1, self.max_pages + 1):
                url = f"{self.base_url}{query}?page={page}"
                try:
                    soup = self.soup(url)
                except Exception:
                    continue
                opportunities.extend(self._parse_listing_page(soup, url))
        return opportunities

    def _parse_listing_page(self, soup: BeautifulSoup, source_url: str) -> list[Opportunity]:
        cards = soup.select(".j-search-result__result, article, .job, .lister__item, .search-result, li")
        opportunities: list[Opportunity] = []
        for card in cards:
            link = card.select_one("a[href*='/job/'], a[href*='jobs.ac.uk/job/']")
            if not link:
                continue

            title = normalize_whitespace(link.get_text(" ", strip=True))
            if not title or len(title) < 6:
                continue

            url = urljoin(source_url, link.get("href", ""))
            text = normalize_whitespace(card.get_text(" ", strip=True))
            deadline = extract_deadline_info(text)
            institution = _extract_first_match(
                card,
                [".j-search-result__employer", ".company", ".institution", "[class*='employer']"],
            )
            location = _extract_labeled_value(card, "Location") or _extract_first_match(card, [".location", "[class*='location']"])
            salary = _extract_labeled_value(card, "Salary") or _extract_first_match(card, [".salary", "[class*='salary']"])
            department = _extract_first_match(card, [".j-search-result__department", ".department", "[class*='department']"])
            posted = _extract_posted_date(text)
            opportunity_type = _infer_type(title)
            detail = self._fetch_detail(url)
            detail_text = detail.get("text", "")
            detail_deadline = extract_deadline_info(detail_text) if detail_text else deadline
            if detail.get("closes"):
                detail_deadline = extract_deadline_info(f"Closes: {detail['closes']}")
            posted_date = detail.get("placed_on") or posted
            salary_value = detail.get("salary") or salary
            location_value = detail.get("location") or location
            department_value = detail.get("department") or department
            institution_value = detail.get("institution") or institution

            opportunities.append(
                Opportunity(
                    type=opportunity_type,
                    title=title,
                    institution=institution_value,
                    department=department_value,
                    location=location_value,
                    country=_infer_country(location_value, institution_value, "United Kingdom"),
                    salary=salary_value,
                    posted_date=posted_date,
                    application_deadline=detail_deadline.date_value.isoformat() if detail_deadline.date_value else "",
                    deadline_status=detail_deadline.label,
                    days_left=detail_deadline.days_left,
                    url=url,
                    source_site="jobs.ac.uk",
                    summary=detail.get("summary") or text[:500],
                    eligibility=detail.get("eligibility", ""),
                    match_score=0.0,
                    match_reason="",
                )
            )
        return opportunities

    def _fetch_detail(self, url: str) -> dict[str, str]:
        try:
            soup = self.soup(url)
        except Exception:
            return {"summary": "", "eligibility": "", "text": "", "placed_on": "", "closes": "", "salary": "", "location": "", "institution": "", "department": ""}

        container = _detail_container(soup)
        page_text = normalize_whitespace(container.get_text(" ", strip=True) if container else soup.get_text(" ", strip=True))
        summary = _extract_summary(container or soup, page_text)
        eligibility = _extract_eligibility(container or soup, page_text)
        meta = _extract_detail_meta(soup)
        return {"summary": summary, "eligibility": eligibility, "text": page_text, **meta}


def _extract_first_match(card: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = card.select_one(selector)
        if node:
            return normalize_whitespace(node.get_text(" ", strip=True))
    return ""


def _extract_labeled_value(card: BeautifulSoup, label: str) -> str:
    target = label.lower()
    for node in card.select("div, span, p"):
        text = normalize_whitespace(node.get_text(" ", strip=True))
        if not text:
            continue
        lower = text.lower()
        if lower.startswith(f"{target}:"):
            return text.split(":", 1)[1].strip()
    return ""


def _extract_posted_date(text: str) -> str:
    lower = text.lower()
    for marker in ["date placed", "placed on", "posted", "published"]:
        idx = lower.find(marker)
        if idx >= 0:
            snippet = text[idx: idx + 80].strip(" .,:;")
            snippet = snippet.split("Closes", 1)[0].strip()
            return snippet
    return ""


def _infer_country(location: str, institution: str, default: str) -> str:
    haystack = f"{location} {institution}".lower()
    if not haystack.strip():
        return default
    if "uk" in haystack or "united kingdom" in haystack or "england" in haystack or "scotland" in haystack:
        return "United Kingdom"
    if "denmark" in haystack:
        return "Denmark"
    if "germany" in haystack:
        return "Germany"
    if "netherlands" in haystack:
        return "Netherlands"
    if "sweden" in haystack:
        return "Sweden"
    return default


def _infer_type(title: str) -> str:
    lower = title.lower()
    fellowship_markers = ["fellowship", "scholarship", "studentship", "postdoctoral", "phd "]
    if any(marker in lower for marker in fellowship_markers):
        return "fellowship"
    return "job"


def _detail_container(soup: BeautifulSoup) -> BeautifulSoup | None:
    selectors = [
        ".j-job-detail",
        ".job-description",
        ".vacancy-details",
        ".content",
        "main",
        "article",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node
    return None


def _extract_summary(container: BeautifulSoup, page_text: str) -> str:
    candidates = []
    for selector in [".j-job-description", ".job-description", ".description", ".content-body"]:
        node = container.select_one(selector)
        if node:
            candidates.append(normalize_whitespace(node.get_text(" ", strip=True)))

    if not candidates:
        paragraphs = [normalize_whitespace(node.get_text(" ", strip=True)) for node in container.select("p")]
        candidates.extend(paragraph for paragraph in paragraphs if len(paragraph) > 80)

    source = max(candidates, key=len) if candidates else _body_excerpt(page_text)
    sentences = sentence_chunks(source)
    return " ".join(sentences[:6])[:1500]


def _extract_eligibility(container: BeautifulSoup, page_text: str) -> str:
    headings = [
        "eligibility",
        "requirements",
        "essential criteria",
        "person specification",
        "about you",
        "candidate profile",
        "qualifications",
    ]
    text_source = normalize_whitespace(_body_excerpt(page_text))
    lower = text_source.lower()
    for heading in headings:
        idx = lower.find(heading)
        if idx >= 0:
            return text_source[idx: idx + 700].strip()

    bullets = [normalize_whitespace(li.get_text(" ", strip=True)) for li in container.select("li")]
    filtered = [item for item in bullets if len(item) > 20]
    return " ".join(filtered[:6])[:700]


def _body_excerpt(page_text: str) -> str:
    text = normalize_whitespace(page_text)
    lower = text.lower()

    start_markers = [
        "applications are invited",
        "the successful applicant",
        "about the role",
        "job description",
        "this position",
        "we are seeking",
        "we seek",
    ]
    start_index = 0
    for marker in start_markers:
        idx = lower.find(marker)
        if idx >= 0:
            start_index = idx
            break

    excerpt = text[start_index:]

    end_markers = [
        "informal enquiries",
        "for further particulars",
        "apply online",
        "share this job",
        "send to a friend",
        "email details to a friend",
        "jobs by email",
        "further details",
        "how to apply",
    ]
    excerpt_lower = excerpt.lower()
    end_index = len(excerpt)
    for marker in end_markers:
        idx = excerpt_lower.find(marker)
        if idx >= 0:
            end_index = min(end_index, idx)

    return excerpt[:end_index].strip()


def _extract_detail_meta(soup: BeautifulSoup) -> dict[str, str]:
    meta = {
        "placed_on": "",
        "closes": "",
        "salary": "",
        "location": "",
        "institution": "",
        "department": "",
    }

    for row in soup.select("tr"):
        header = row.select_one("th")
        value = row.select_one("td")
        if not header or not value:
            continue
        label = normalize_whitespace(header.get_text(" ", strip=True)).lower().rstrip(":")
        cell = normalize_whitespace(value.get_text(" ", strip=True))
        if not cell:
            continue
        if label == "placed on":
            meta["placed_on"] = _normalize_date_text(cell)
        elif label in {"closes", "closing date"}:
            meta["closes"] = _normalize_date_text(cell)
        elif label == "salary":
            meta["salary"] = cell
        elif label == "location":
            meta["location"] = cell

    heading_candidates = [
        ".j-job-header__employer",
        ".j-job-details__employer",
        ".j-job-detail__employer",
        "[class*='employer']",
    ]
    for selector in heading_candidates:
        node = soup.select_one(selector)
        if node:
            meta["institution"] = normalize_whitespace(node.get_text(" ", strip=True))
            break

    dept_candidates = [
        ".j-job-header__department",
        ".j-job-details__department",
        ".j-job-detail__department",
        "[class*='department']",
    ]
    for selector in dept_candidates:
        node = soup.select_one(selector)
        if node:
            meta["department"] = normalize_whitespace(node.get_text(" ", strip=True))
            break

    return meta


def _normalize_date_text(value: str) -> str:
    return re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", value, flags=re.I)

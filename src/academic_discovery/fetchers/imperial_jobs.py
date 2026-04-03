from __future__ import annotations

from urllib.parse import parse_qs, unquote_plus, urljoin, urlparse
from io import BytesIO
import re

from bs4 import BeautifulSoup
from pypdf import PdfReader

from academic_discovery.fetchers.base import DynamicListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class ImperialJobsFetcher(DynamicListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 40, max_show_more_clicks: int = 8) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results
        self.max_show_more_clicks = max_show_more_clicks

    def collect_items_static(self) -> list[dict[str, str]]:
        soup = self.soup(self.base_url)
        return _extract_listing_items(soup, self.base_url, self.max_results)

    def collect_items_dynamic(self) -> list[dict[str, str]]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                return self._collect_detail_items(browser)
            finally:
                browser.close()

    def fetch_dynamic_details(self, detail_items: list[dict[str, str]]) -> list[Opportunity]:
        from playwright.sync_api import sync_playwright

        opportunities: list[Opportunity] = []
        detail_success = 0
        detail_failed = 0
        parser_failures = 0
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for item in detail_items:
                    try:
                        opportunity = self._fetch_detail(item, browser)
                    except Exception:
                        detail_failed += 1
                        continue
                    if opportunity is None:
                        parser_failures += 1
                        continue
                    detail_success += 1
                    opportunities.append(opportunity)
            finally:
                browser.close()
        self.update_diagnostics(
            detail_success=detail_success,
            detail_failed=detail_failed,
            parser_failures=parser_failures,
        )
        return opportunities

    def fetch_static_details(self, detail_items: list[dict[str, str]]) -> list[Opportunity]:
        opportunities = self._fetch_static_details(detail_items)
        self.update_diagnostics(
            detail_success=len(opportunities),
            detail_failed=max(0, len(detail_items) - len(opportunities)),
            parser_failures=max(0, len(detail_items) - len(opportunities)),
        )
        return opportunities

    def _collect_detail_items(self, browser) -> list[dict[str, str]]:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        items: list[dict[str, str]] = []
        page = browser.new_page()
        page.goto(self.base_url, wait_until="networkidle", timeout=60000)

        for _ in range(self.max_show_more_clicks):
            try:
                button = page.get_by_role("button", name="Show more results")
                if button.count() == 0:
                    break
                button.first.click(timeout=3000)
                page.wait_for_timeout(1200)
            except PlaywrightTimeoutError:
                break
            except Exception:
                break

        html = page.content()
        page.close()

        soup = BeautifulSoup(html, "html.parser")
        return _extract_listing_items(soup, self.base_url, self.max_results)

    def _fetch_detail(self, item: dict[str, str], browser) -> Opportunity | None:
        url = item["url"]
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        html = page.content()
        page.close()
        soup = BeautifulSoup(html, "html.parser")
        text = normalize_whitespace(soup.get_text(" ", strip=True))
        title = item.get("title") or _first_text(soup, ["h1", "title"])
        if not title or not _looks_like_imperial_job_detail(title, text, url):
            return None

        listing_text = item.get("listing_text", "")
        deadline = extract_deadline_info(text)
        listing_deadline = extract_deadline_info(listing_text) if listing_text else deadline
        pdf_text = self._job_description_pdf_text(soup, url)
        effective_text = pdf_text or text
        summary = _detail_summary(effective_text)
        if _is_generic_imperial_summary(summary):
            summary = listing_text or summary
        eligibility = _detail_eligibility(effective_text)

        return Opportunity(
            type=_infer_type(title),
            title=title,
            institution="Imperial College London",
            department=(
                _extract_label(listing_text, ["Department", "Faculty", "Academic Department"])
                or _extract_label(text, ["Department", "Faculty", "Academic Department"])
            )[:180],
            location=(_extract_label(listing_text, ["Location", "Campus"]) or _extract_label(text, ["Location", "Campus"]))[:140],
            country="United Kingdom",
            salary=(_extract_label(listing_text, ["Salary", "Starting salary", "Salary range"]) or _extract_label(text, ["Salary", "Starting salary", "Salary range"]))[:140],
            posted_date=(_extract_label(listing_text, ["Posted on", "Placed on", "Date posted"]) or _extract_label(text, ["Posted on", "Placed on", "Date posted"]))[:140],
            application_deadline=(listing_deadline.date_value or deadline.date_value).isoformat() if (listing_deadline.date_value or deadline.date_value) else "",
            deadline_status=(listing_deadline.label if listing_deadline.date_value else deadline.label),
            days_left=(listing_deadline.days_left if listing_deadline.date_value else deadline.days_left),
            url=url,
            source_site=urlparse(self.base_url).netloc,
            summary=summary,
            eligibility=eligibility,
            match_score=0.0,
            match_reason="",
        )

    def _fetch_static_details(self, detail_items: list[dict[str, str]]) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for item in detail_items:
            try:
                soup = self.soup(item["url"])
            except Exception:
                continue
            text = normalize_whitespace(soup.get_text(" ", strip=True))
            title = item.get("title") or _first_text(soup, ["h1", "title"])
            if not title or not _looks_like_imperial_job_detail(title, text, item["url"]):
                continue
            listing_text = item.get("listing_text", "")
            deadline = extract_deadline_info(text)
            listing_deadline = extract_deadline_info(listing_text) if listing_text else deadline
            summary = _detail_summary(text)
            if _is_generic_imperial_summary(summary):
                summary = listing_text or summary
            eligibility = _detail_eligibility(text)
            opportunities.append(
                Opportunity(
                    type=_infer_type(title),
                    title=title,
                    institution="Imperial College London",
                    department=(
                        _extract_label(listing_text, ["Departments", "Department", "Faculty", "Academic Department"])
                        or _extract_label(text, ["Departments", "Department", "Faculty", "Academic Department"])
                    )[:180],
                    location=(_extract_label(listing_text, ["Location/campus", "Location", "Campus"]) or _extract_label(text, ["Location/campus", "Location", "Campus"]))[:140],
                    country="United Kingdom",
                    salary=(_extract_label(listing_text, ["Salary or Salary range", "Salary", "Starting salary", "Salary range"]) or _extract_label(text, ["Salary or Salary range", "Salary", "Starting salary", "Salary range"]))[:140],
                    posted_date=(_extract_label(listing_text, ["Posted on", "Placed on", "Date posted", "Posting End Date"]) or _extract_label(text, ["Posted on", "Placed on", "Date posted"]))[:140],
                    application_deadline=(listing_deadline.date_value or deadline.date_value).isoformat() if (listing_deadline.date_value or deadline.date_value) else "",
                    deadline_status=(listing_deadline.label if listing_deadline.date_value else deadline.label),
                    days_left=(listing_deadline.days_left if listing_deadline.date_value else deadline.days_left),
                    url=item["url"],
                    source_site=urlparse(self.base_url).netloc,
                    summary=summary,
                    eligibility=eligibility,
                    match_score=0.0,
                    match_reason="",
                )
            )
        return opportunities

    def _job_description_pdf_text(self, soup: BeautifulSoup, base_url: str) -> str:
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            label = normalize_whitespace(anchor.get_text(" ", strip=True)).lower()
            if ".pdf" not in href.lower() and "job description" not in label:
                continue
            pdf_url = urljoin(base_url, href)
            try:
                response = self.get(pdf_url)
                content_type = str(response.headers.get("Content-Type", "") or "").lower()
                if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
                    continue
                reader = PdfReader(BytesIO(response.content))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                cleaned = normalize_whitespace(text)
                if len(cleaned) > 200:
                    return cleaned
            except Exception:
                continue
        return ""


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
        if idx >= 0:
            fragment = text[idx + len(label): idx + len(label) + 180]
            cleaned = fragment.split("See job details", 1)[0]
            cleaned = cleaned.split("Apply now", 1)[0]
            cleaned = re.split(r"\s{2,}|(?=(?:Job Advertisement title|Faculties|Departments|Job category|Salary or Salary range|Location/campus|Contract type work pattern|Posting End Date)\b)", cleaned, maxsplit=1)[0]
            return cleaned.strip(" .,:;")
    return ""


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    raw = params.get("jobTitle", [""])[0]
    return normalize_whitespace(unquote_plus(raw))


def _listing_context_text(anchor: BeautifulSoup) -> str:
    node = anchor
    best = ""
    for _ in range(6):
        node = node.parent
        if not getattr(node, "get_text", None):
            break
        text = normalize_whitespace(node.get_text(" ", strip=True))
        if len(text) > len(best):
            best = text
        if len(text) > 180:
            break
    return best


def _extract_listing_items(soup: BeautifulSoup, base_url: str, max_results: int) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href*='/jobs/search-jobs/description/']"):
        href = anchor.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        title = normalize_whitespace(anchor.get_text(" ", strip=True))
        if title.lower() == "see job details":
            title = _title_from_url(url)
        if not title:
            title = _title_from_url(url)
        listing_text = _listing_context_text(anchor)
        if "job advertisement title" not in listing_text.lower() and "salary or salary range" not in listing_text.lower():
            continue
        seen.add(url)
        items.append(
            {
                "url": url,
                "title": title,
                "listing_text": listing_text,
            }
        )
        if len(items) >= max_results:
            break
    return items


def _looks_like_imperial_job_detail(title: str, text: str, url: str) -> bool:
    haystack = f"{title} {text[:2500]} {url}".lower()
    markers = ["apply", "salary", "job details", "closing date", "deadline", "job ref", "imperial college london"]
    return any(marker in haystack for marker in markers)


def _detail_summary(text: str) -> str:
    excerpt = _body_excerpt(text)
    sentences = sentence_chunks(excerpt)
    return " ".join(sentences[:6])[:1600]


def _detail_eligibility(text: str) -> str:
    excerpt = _body_excerpt(text)
    lower = excerpt.lower()
    for marker in ["requirements", "essential requirements", "experience", "you should have", "about you"]:
        idx = lower.find(marker)
        if idx >= 0:
            return excerpt[idx: idx + 800].strip()
    return ""


def _body_excerpt(text: str) -> str:
    cleaned = normalize_whitespace(text)
    lower = cleaned.lower()
    disclaimer_markers = [
        "job descriptions cannot be exhaustive",
        "please note that job descriptions are not exhaustive",
    ]
    for marker in disclaimer_markers:
        idx = lower.find(marker)
        if idx == 0 or idx < 80:
            later_markers = [
                "job purpose",
                "main duties and responsibilities",
                "duties and responsibilities",
                "summary of duties",
                "role purpose",
                "about the role",
                "what you would be doing",
                "what we are looking for",
                "you will",
            ]
            for later in later_markers:
                later_idx = lower.find(later)
                if later_idx > idx + 120:
                    cleaned = cleaned[later_idx:]
                    lower = cleaned.lower()
                    break

    start_markers = [
        "job purpose",
        "job description",
        "about the role",
        "duties and responsibilities",
        "main duties",
        "main duties and responsibilities",
        "summary of duties",
        "role purpose",
        "what you would be doing",
        "what we are looking for",
        "the role",
        "we are seeking",
        "you will",
    ]
    start = 0
    for marker in start_markers:
        idx = lower.find(marker)
        if idx >= 0:
            start = idx
            break

    excerpt = cleaned[start:]
    end_markers = [
        "apply now",
        "how to apply",
        "further information",
        "equality",
        "closing date",
        "deadline",
        "job details",
        "please note that job descriptions",
    ]
    excerpt_lower = excerpt.lower()
    end = len(excerpt)
    for marker in end_markers:
        idx = excerpt_lower.find(marker)
        if idx > 200:
            end = min(end, idx)
    return excerpt[:end].strip()


def _infer_type(title: str) -> str:
    lower = title.lower()
    if any(marker in lower for marker in ["fellowship", "studentship", "scholarship", "postdoctoral", "phd "]):
        return "fellowship"
    return "job"


def _is_generic_imperial_summary(summary: str) -> bool:
    lower = summary.lower()
    markers = [
        "job descriptions cannot be exhaustive",
        "please note that job descriptions are not exhaustive",
        "our values are at the root of everything we do",
    ]
    return any(marker in lower for marker in markers)

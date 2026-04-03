from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import StaticListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class MelbourneJobsFetcher(StaticListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 80) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href*='/en/job/'], a[href*='/caw/en/job/']"):
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
        summary_source = _section_text(text, ["About the Role", "Position Description", "Job no:"])
        return Opportunity(
            type=_infer_type(title, text),
            title=title,
            institution="The University of Melbourne",
            department=_extract_label(text, ["Department", "School", "Faculty"])[:180],
            location=(_extract_label(text, ["Location"]) or "Melbourne")[:140],
            country="Australia",
            salary=_extract_label(text, ["Salary", "Remuneration"])[:140],
            posted_date=_extract_label(text, ["Published on", "Date posted"])[:140],
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=" ".join(sentence_chunks(summary_source or text)[:6])[:1600],
            eligibility=_section_text(text, ["Who We Are Looking For", "Selection Criteria", "Qualifications"])[:800],
            match_score=0.0,
            match_reason="",
        )


def _looks_like_detail(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("unimelb.edu.au") and ("/en/job/" in parsed.path or "/caw/en/job/" in parsed.path)


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
    for label in labels:
        idx = lower.find(label.lower())
        if idx < 0:
            continue
        fragment = text[idx + len(label): idx + len(label) + 220].strip(" .,:;-")
        for stop in ["about the role", "who we are looking for", "salary", "location", "department", "faculty", "published on", "closing date"]:
            if stop == label.lower():
                continue
            pos = fragment.lower().find(stop)
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
        for stop in ["Who We Are Looking For", "Selection Criteria", "Equal Opportunity", "Applications close"]:
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
    include = ["research", "postdoc", "postdoctoral", "fellow", "professor", "lecturer", "assistant professor", "researcher"]
    exclude = ["clinical", "medicine", "social work", "teaching specialist", "manager", "administrator"]
    return any(marker in lower for marker in include) and not any(marker in lower for marker in exclude)

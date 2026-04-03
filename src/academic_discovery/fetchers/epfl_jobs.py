from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import StaticListDetailFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class EPFLJobsFetcher(StaticListDetailFetcher):
    def __init__(self, base_url: str, max_results: int = 80) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href*='/job/']"):
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
        summary_source = _section_text(text, ["Description", "Job Description", "Votre mission", "Mission"])
        return Opportunity(
            type=_infer_type(title, text),
            title=title,
            institution="EPFL",
            department=_extract_label(text, ["School", "Institute", "Faculty", "Laboratory"])[:180],
            location=(_extract_location(text) or "Lausanne")[:140],
            country="Switzerland",
            salary=_extract_label(text, ["Salary", "Activity rate"])[:140],
            posted_date=_extract_label(text, ["Publication date", "Published"])[:140],
            application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
            deadline_status=deadline.label,
            days_left=deadline.days_left,
            url=item["url"],
            source_site=urlparse(self.base_url).netloc,
            summary=" ".join(sentence_chunks(summary_source or text)[:6])[:1600],
            eligibility=_section_text(text, ["Profile", "Your profile", "Requirements", "Candidate Profile"])[:800],
            match_score=0.0,
            match_reason="",
        )


def _looks_like_detail(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("epfl.ch") and "/job/" in parsed.path


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
    stops = ["publication date", "activity rate", "contract type", "reference", "description", "profile", "requirements", "school", "institute", "location"]
    for label in labels:
        idx = lower.find(label.lower())
        if idx < 0:
            continue
        fragment = text[idx + len(label): idx + len(label) + 180].strip(" .,:;-")
        cutoff = len(fragment)
        for stop in stops:
            pos = fragment.lower().find(stop.lower())
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
        for stop in ["Profile", "Your profile", "Requirements", "Contract Start Date", "Reference", "Publication date", "Apply now"]:
            pos = section.lower().find(stop.lower())
            if pos > 120:
                section = section[:pos]
                break
        return normalize_whitespace(section)
    return ""


def _extract_location(text: str) -> str:
    match = re.search(r"\b(Lausanne|Geneva|Gen[eè]ve|Neuch[aâ]tel|Sion|Fribourg)\b", text, re.I)
    return normalize_whitespace(match.group(0)) if match else ""


def _infer_type(title: str, text: str) -> str:
    haystack = f"{title} {text}".lower()
    if any(marker in haystack for marker in ["phd", "studentship", "fellowship", "scholarship"]):
        return "fellowship"
    return "job"


def _is_relevant_title(title: str) -> bool:
    lower = title.lower()
    include = ["research", "postdoc", "postdoctoral", "fellow", "scientist", "engineer", "professor", "lecturer", "doctoral", "phd"]
    exclude = ["assistant administratif", "administrative", "secretary", "manager", "legal", "finance", "hr"]
    return any(marker in lower for marker in include) and not any(marker in lower for marker in exclude)

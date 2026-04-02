from __future__ import annotations

from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

from academic_discovery.fetchers.base import BaseFetcher
from academic_discovery.models import Opportunity
from academic_discovery.utils.deadlines import extract_deadline_info
from academic_discovery.utils.text import normalize_whitespace, sentence_chunks


class ImperialFellowshipsFetcher(BaseFetcher):
    def __init__(self, base_url: str, max_results: int = 200) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_results = max_results

    def fetch(self) -> list[Opportunity]:
        soup = self.soup(self.base_url)
        opportunities: list[Opportunity] = []
        for table in soup.select("table"):
            for row in table.select("tr"):
                cells = row.select("td")
                if len(cells) < 4:
                    continue
                title_anchor = cells[0].select_one("a[href]")
                title = normalize_whitespace(cells[0].get_text(" ", strip=True))
                if not title:
                    continue
                details = normalize_whitespace(cells[1].get_text(" ", strip=True))
                duration = normalize_whitespace(cells[2].get_text(" ", strip=True))
                deadline_text = normalize_whitespace(cells[3].get_text(" ", strip=True))
                deadline = extract_deadline_info(
                    deadline_text.replace("Opened:", "Open date:").replace("Closed:", "Close date:")
                )
                detail_url = ""
                if title_anchor and title_anchor.get("href"):
                    detail_url = urljoin(self.base_url, title_anchor["href"])
                else:
                    detail_url = self.base_url + "#imperial-fellowship-" + str(len(opportunities) + 1)

                summary_parts = [details]
                if duration:
                    summary_parts.append(f"Duration: {duration}")
                summary = " ".join(sentence_chunks(" ".join(summary_parts))[:6])[:1600]
                opportunities.append(
                    Opportunity(
                        type="fellowship",
                        title=title,
                        institution="Imperial College London",
                        department="Early Career Researcher Institute",
                        location="London",
                        country="United Kingdom",
                        salary="",
                        posted_date="",
                        application_deadline=deadline.date_value.isoformat() if deadline.date_value else "",
                        deadline_status=deadline.label if deadline.label != "unknown deadline" else deadline_text or "listed deadline",
                        days_left=deadline.days_left,
                        url=detail_url,
                        source_site=urlparse(self.base_url).netloc,
                        summary=summary,
                        eligibility=details[:900],
                        match_score=0.0,
                        match_reason="",
                    )
                )
                if len(opportunities) >= self.max_results:
                    return opportunities
        return opportunities

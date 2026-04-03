from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup


@dataclass
class FetcherDiagnostics:
    list_count: int = 0
    detail_success: int = 0
    detail_failed: int = 0
    dynamic_source: bool = False
    fallback_used: bool = False
    fetch_mode: str = "static"
    parser_failures: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "list_count": self.list_count,
            "detail_success": self.detail_success,
            "detail_failed": self.detail_failed,
            "dynamic_source": self.dynamic_source,
            "fallback_used": self.fallback_used,
            "fetch_mode": self.fetch_mode,
            "parser_failures": self.parser_failures,
            "error": self.error,
        }


class BaseFetcher(ABC):
    user_agent = "AcademicDiscovery/0.1 (+https://local)"
    dynamic_source = False

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        # Ignore broken system proxy settings by default so direct crawling still works.
        self.session.trust_env = False
        self._diagnostics = FetcherDiagnostics(dynamic_source=self.dynamic_source)

    def get(self, url: str) -> requests.Response:
        response = self.session.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
        )
        response.raise_for_status()
        return response

    def soup(self, url: str) -> BeautifulSoup:
        response = self.get(url)
        return BeautifulSoup(response.text, "html.parser")

    def update_diagnostics(self, **values: object) -> None:
        for key, value in values.items():
            if hasattr(self._diagnostics, key):
                setattr(self._diagnostics, key, value)

    def diagnostics(self) -> dict[str, object]:
        return self._diagnostics.to_dict()

    @abstractmethod
    def fetch(self) -> list:
        raise NotImplementedError


class StaticListDetailFetcher(BaseFetcher):
    def fetch(self) -> list:
        soup = self.soup(self.base_url)
        items = self.collect_items(soup)
        opportunities: list = []
        detail_success = 0
        detail_failed = 0
        parser_failures = 0
        self.update_diagnostics(list_count=len(items), fetch_mode="static")

        for item in items:
            try:
                detail_soup = self.soup(item["url"])
                opportunity = self.extract_detail(item, detail_soup)
            except Exception:
                detail_failed += 1
                continue
            if opportunity is None:
                parser_failures += 1
                continue
            detail_success += 1
            opportunities.append(opportunity)

        self.update_diagnostics(
            detail_success=detail_success,
            detail_failed=detail_failed,
            parser_failures=parser_failures,
        )
        return opportunities

    @abstractmethod
    def collect_items(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def extract_detail(self, item: dict[str, str], soup: BeautifulSoup):
        raise NotImplementedError


class DynamicListDetailFetcher(BaseFetcher):
    dynamic_source = True

    def fetch(self) -> list:
        static_items = self.collect_items_static()
        self.update_diagnostics(list_count=len(static_items), dynamic_source=True, fetch_mode="static")

        if not self.playwright_available():
            self.update_diagnostics(fallback_used=True, fetch_mode="static")
            return self.fetch_static_details(static_items)

        try:
            detail_items = self.collect_items_dynamic() or static_items
            self.update_diagnostics(list_count=len(detail_items), fetch_mode="dynamic")
            return self.fetch_dynamic_details(detail_items)
        except Exception as exc:
            self.update_diagnostics(
                fallback_used=True,
                fetch_mode="static",
                error=str(exc),
            )
            return self.fetch_static_details(static_items)

    def playwright_available(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception:
            return False
        return True

    @abstractmethod
    def collect_items_static(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def collect_items_dynamic(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_dynamic_details(self, detail_items: list[dict[str, str]]) -> list:
        raise NotImplementedError

    @abstractmethod
    def fetch_static_details(self, detail_items: list[dict[str, str]]) -> list:
        raise NotImplementedError


class SinglePageListingFetcher(BaseFetcher):
    def fetch(self) -> list:
        soup = self.soup(self.base_url)
        opportunities = self.extract_from_soup(soup, self.base_url)
        self.update_diagnostics(
            list_count=1,
            detail_success=len(opportunities),
            detail_failed=0,
            parser_failures=0 if opportunities else 1,
            fetch_mode="static",
        )
        return opportunities

    @abstractmethod
    def extract_from_soup(self, soup: BeautifulSoup, page_url: str) -> list:
        raise NotImplementedError

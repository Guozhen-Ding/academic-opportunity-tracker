from __future__ import annotations

from abc import ABC, abstractmethod

import requests
from bs4 import BeautifulSoup


class BaseFetcher(ABC):
    user_agent = "AcademicDiscovery/0.1 (+https://local)"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        # Ignore broken system proxy settings by default so direct crawling still works.
        self.session.trust_env = False

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

    @abstractmethod
    def fetch(self) -> list:
        raise NotImplementedError

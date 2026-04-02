from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class CandidateProfile:
    raw_text: str
    research_interests: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class DeadlineInfo:
    label: str = "unknown deadline"
    date_value: date | None = None
    days_left: int | None = None
    notes: str | None = None


@dataclass
class Opportunity:
    type: str
    title: str
    institution: str
    department: str
    location: str
    country: str
    salary: str
    posted_date: str
    application_deadline: str
    deadline_status: str
    days_left: int | None
    url: str
    source_site: str
    summary: str
    eligibility: str
    source_key: str = ""
    status: str = ""
    note: str = ""
    match_score: float = 0.0
    match_reason: str = ""
    matched_keywords: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "title": self.title,
            "institution": self.institution,
            "department": self.department,
            "location": self.location,
            "country": self.country,
            "salary": self.salary,
            "posted_date": self.posted_date,
            "application_deadline": self.application_deadline,
            "deadline_status": self.deadline_status,
            "days_left": self.days_left,
            "url": self.url,
            "source_site": self.source_site,
            "source_key": self.source_key,
            "summary": self.summary,
            "eligibility": self.eligibility,
            "status": self.status,
            "note": self.note,
            "match_score": round(self.match_score, 3),
            "match_reason": self.match_reason,
            "matched_keywords": self.matched_keywords,
        }

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as date_parser

from academic_discovery.models import DeadlineInfo
from academic_discovery.utils.text import normalize_whitespace


SPECIAL_CASES = [
    (r"open until filled", "open until filled"),
    (r"rolling deadline", "rolling deadline"),
    (r"review begins on", "review begins on"),
    (r"review of applications begins", "review begins on"),
    (r"deadline[:\s]+tba", "unknown deadline"),
]


def extract_deadline_info(text: str, today: date | None = None) -> DeadlineInfo:
    today = today or date.today()
    normalized = normalize_whitespace(text).lower()

    for pattern, label in SPECIAL_CASES:
        if re.search(pattern, normalized):
            parsed_date = None
            if label == "review begins on":
                parsed_date = _extract_labeled_date(
                    text,
                    labels=["review begins on", "review of applications begins"],
                    today=today,
                )
            days_left = (parsed_date - today).days if parsed_date else None
            return DeadlineInfo(label=label, date_value=parsed_date, days_left=days_left)

    labeled_deadline = _extract_labeled_date(
        text,
        labels=["close date", "closes", "closing date", "deadline", "apply by", "application deadline"],
        today=today,
    )
    if labeled_deadline:
        return DeadlineInfo(
            label="fixed deadline",
            date_value=labeled_deadline,
            days_left=(labeled_deadline - today).days,
        )

    if "open date" in normalized and "close date" not in normalized and "closing date" not in normalized and "closes" not in normalized:
        return DeadlineInfo(label="unknown deadline")

    return DeadlineInfo(label="unknown deadline")


def _extract_first_date(text: str) -> date | None:
    cleaned = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.I)
    patterns = [
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b",
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\b",
        r"\b[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        try:
            return date_parser.parse(match.group(0), fuzzy=True, dayfirst=True).date()
        except (ValueError, OverflowError):
            continue

    fuzzy_tokens = re.findall(r"(deadline|apply by|closing date|closes|review begins on)(.{0,80})", cleaned, re.I)
    for _, fragment in fuzzy_tokens:
        try:
            parsed = date_parser.parse(fragment, fuzzy=True, default=datetime(2100, 1, 1))
            if parsed.year != 2100:
                return parsed.date()
        except (ValueError, OverflowError):
            continue
    return None


def _extract_labeled_date(text: str, labels: list[str], today: date | None = None) -> date | None:
    today = today or date.today()
    cleaned = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.I)
    found_dates: list[date] = []
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:\-]?\s*([^\n\r|]{{0,40}})"
        for match in re.finditer(pattern, cleaned, re.I):
            fragment = match.group(1).strip()
            parsed = _extract_first_date(fragment)
            if parsed:
                found_dates.append(parsed)
    if not found_dates:
        return None
    upcoming = sorted(value for value in found_dates if value >= today)
    if upcoming:
        return upcoming[0]
    return sorted(found_dates)[-1]

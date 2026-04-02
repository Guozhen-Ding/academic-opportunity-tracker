from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from academic_discovery.models import CandidateProfile
from academic_discovery.utils.text import extract_keywords, find_section, normalize_whitespace


SECTION_MAP = {
    "research_interests": ["Research Interests", "Research Profile", "Interests"],
    "methods": ["Methods", "Methodological Expertise", "Research Methods"],
    "skills": ["Skills", "Technical Skills", "Core Skills"],
}


def extract_profile_from_pdf(path: str | Path) -> CandidateProfile:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    normalized = normalize_whitespace(text)

    sections = {
        key: _split_items(find_section(text, headings))
        for key, headings in SECTION_MAP.items()
    }

    keywords = extract_keywords(normalized)
    return CandidateProfile(
        raw_text=normalized,
        research_interests=sections["research_interests"],
        methods=sections["methods"],
        skills=sections["skills"],
        keywords=keywords,
    )


def _split_items(section_text: str) -> list[str]:
    if not section_text:
        return []
    chunks = [part.strip(" -;,.") for part in section_text.replace("•", "\n").split("\n")]
    output: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        output.extend(part.strip() for part in chunk.split(",") if part.strip())
    return output[:20]

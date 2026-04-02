from __future__ import annotations

from academic_discovery.models import CandidateProfile, Opportunity
from academic_discovery.utils.text import extract_keywords, normalize_whitespace


NOISY_TERMS = {
    "ding",
    "feng",
    "oct",
    "sep",
    "jun",
    "aug",
    "dec",
    "nov",
    "mar",
    "apr",
    "may",
    "r",
}

DEFAULT_EXPANDED_TERMS = {
    "decarbonisation",
    "decarbonization",
    "net zero",
    "energy materials",
    "energy systems",
    "sustainable materials",
    "sustainable technologies",
    "sustainability",
    "structural integrity",
    "computational mechanics",
    "multiscale modelling",
    "multiscale modeling",
    "simulation",
    "finite element",
    "molecular simulation",
    "fracture",
    "durability",
    "resilience",
    "hydrogen safety",
    "hydrogen infrastructure",
    "composites",
    "polymer engineering",
    "materials science",
    "materials chemistry",
}

DEFAULT_PROTECTED_TERMS = {
    "fellowship",
    "research fellow",
    "research fellowship",
    "postdoctoral",
    "postdoc",
    "phd",
    "studentship",
    "scholarship",
    "civil engineering",
    "structural engineering",
    "materials engineering",
    "mechanical engineering",
    "chemical engineering",
    "hydrogen",
    "polymer",
    "polyethylene",
    "composite",
    "cfrp",
    "abaqus",
    "lammps",
}

DEFAULT_BROAD_TERMS = {
    "research associate",
    "research assistant",
    "research fellow",
    "postdoctoral",
    "lecturer",
    "assistant professor",
    "associate professor",
    "professor",
    "scientist",
    "engineer",
    "engineering",
    "materials",
    "mechanics",
    "modelling",
    "modeling",
    "simulation",
    "hydrogen",
    "polymer",
    "composite",
    "energy",
    "sustainable",
    "decarbonisation",
    "decarbonization",
    "net zero",
    "fellowship",
    "studentship",
    "phd",
}


def score_opportunity(
    opportunity: Opportunity,
    profile: CandidateProfile,
    extra_keywords: list[str],
    expanded_terms: list[str] | None = None,
) -> tuple[float, str, list[str]]:
    raw_terms = profile.keywords + profile.research_interests + profile.methods + profile.skills + extra_keywords + list(expanded_terms or [])
    profile_terms = {
        term.lower().strip()
        for term in raw_terms
        if term and len(term.strip()) >= 4 and term.lower().strip() not in NOISY_TERMS
    }
    haystack = normalize_whitespace(
        " ".join(
            [
                opportunity.title,
                opportunity.institution,
                opportunity.department,
                opportunity.summary,
                opportunity.eligibility,
            ]
        )
    ).lower()

    matched = sorted(term for term in profile_terms if term in haystack)
    strong_matches = [
        term for term in matched if term in opportunity.title.lower() or term in opportunity.summary.lower()[:250]
    ]
    score = min(1.0, ((len(matched) * 0.6) + (len(strong_matches) * 0.8)) / max(10, len(profile_terms) or 1))

    if not matched:
        page_keywords = extract_keywords(haystack, top_n=8)
        matched = page_keywords[:3]
        score = min(score, 0.1)

    reason = "Matched on: " + ", ".join(matched[:8]) if matched else "Weak keyword overlap."
    return score, reason, matched[:12]


def should_keep_opportunity(
    opportunity: Opportunity,
    score: float,
    minimum_score: float,
    protected_terms: list[str] | None = None,
    broad_terms: list[str] | None = None,
) -> tuple[bool, str]:
    haystack = normalize_whitespace(
        " ".join(
            [
                opportunity.title,
                opportunity.institution,
                opportunity.department,
                opportunity.summary,
                opportunity.eligibility,
            ]
        )
    ).lower()

    protected = [term for term in (protected_terms or []) if term and term.lower() in haystack]
    broad = [term for term in (broad_terms or []) if term and term.lower() in haystack]

    if opportunity.type == "fellowship":
        return True, "Preserved by broad rule: fellowship"
    if protected:
        return True, "Preserved by protected terms: " + ", ".join(protected[:6])
    if score >= minimum_score:
        return True, "Preserved by score"
    if broad:
        return True, "Preserved by broad academic terms: " + ", ".join(broad[:6])
    return False, "Filtered out: weak score and no protected/broad terms"

"""Explainable priority scoring for scholar deep analysis queue items."""

from datetime import datetime
from typing import List, Optional, Tuple

from app.models.constants import is_pdf_ready_status


VENUE_TIER_SCORES = {
    "A": 10,
    "B": 6,
    "C": 3,
}


def classify_venue_tier(venue: str) -> str:
    value = (venue or "").lower()
    if "science" in value or "nature" in value:
        return "A"
    if "journal" in value or "proceedings" in value:
        return "B"
    if value:
        return "C"
    return "unknown"


def score_queue_item(
    *,
    third_party_status: str,
    self_citation_status: str,
    pdf_readiness_status: str,
    venue_tier: str,
    year: int,
    user_review_status: str = "unreviewed",
    queue_status: str = "pending",
    template_matches: Optional[List[dict]] = None,
) -> Tuple[float, List[dict]]:
    reasons: List[dict] = []

    def add(reason: str, delta: float) -> None:
        reasons.append({"reason": reason, "delta": delta})

    if third_party_status == "third_party":
        add("third_party_citation", 20)
    elif third_party_status == "ambiguous":
        add("ambiguous_third_party_status", 0)

    if self_citation_status == "self_citation":
        add("self_citation_penalty", -25)
    elif self_citation_status == "possible_self_citation":
        add("possible_self_citation_penalty", -10)

    if is_pdf_ready_status(pdf_readiness_status):
        add("pdf_ready", 15)

    venue_delta = VENUE_TIER_SCORES.get(venue_tier or "", 0)
    if venue_delta:
        add(f"venue_tier_{venue_tier.lower()}", venue_delta)

    current_year = datetime.utcnow().year
    if year:
        if year >= current_year - 1:
            add("recent_citing_paper", 5)
        elif year >= current_year - 5:
            add("moderately_recent_citing_paper", 2)

    if user_review_status == "important":
        add("user_marked_important", 100)
    elif user_review_status == "rejected":
        add("user_rejected", -100)

    if queue_status == "skipped":
        add("queue_skipped", -50)

    for match in template_matches or []:
        template = match.get("template")
        template_type = getattr(template, "template_type", "custom")
        terms = ", ".join(match.get("matched_terms", []))
        delta = min(float(match.get("match_score", 0.0)), 30.0)
        if delta:
            add(f"template_match:{template_type}:{terms}", delta)

    return sum(reason["delta"] for reason in reasons), reasons

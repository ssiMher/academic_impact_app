"""Deterministic evidence scoring independent of LLM ordering."""

from app.schemas.evidence import EvidenceScore
from app.schemas.llm import LlmFinding


STRONG_TYPES = {
    "first_or_seminal_claim",
    "detailed_comparison",
    "baseline_or_benchmark",
    "method_foundation",
    "theoretical_foundation",
    "application_extension",
    "positive_evaluation",
    "limitation_or_negative",
    "adopted_or_combined",
    "state_of_the_art_claim",
    "important_author_citation",
    "long_context_citation",
}

WEAK_MENTION_TYPES = {"weak_mention", "background_mention", "passing_mention", "reference_only"}


def strength_for_score(score: float) -> str:
    if score >= 0.8:
        return "strong"
    if score >= 0.6:
        return "moderate"
    return "weak"


def score_finding(finding: LlmFinding) -> EvidenceScore:
    if not finding.citation_text:
        return EvidenceScore(
            score=0.0,
            evidence_strength="none",
            rationale="Finding has no original citation text.",
        )

    if finding.mention_type == "grouped_citation":
        return EvidenceScore(
            score=0.25,
            evidence_strength="weak",
            rationale="Grouped citation is not specific enough for strong evidence.",
        )

    if finding.mention_type == "reference_only":
        return EvidenceScore(
            score=0.0,
            evidence_strength="none",
            rationale="Reference-list entries are not evidence of evaluation or use.",
        )

    if finding.mention_type in WEAK_MENTION_TYPES:
        return EvidenceScore(
            score=0.35,
            evidence_strength="weak",
            rationale="Weak or passing mention is not specific enough for strong evidence.",
        )

    score = 0.5
    if finding.evidence_type in STRONG_TYPES:
        score += 0.25
    if finding.stance in {"positive", "mixed"}:
        score += 0.1
    if len(finding.citation_text) >= 80:
        score += 0.05

    score = min(score, 0.95)
    strength = strength_for_score(score)

    return EvidenceScore(
        score=score,
        evidence_strength=strength,
        rationale="Score combines evidence type, stance, specificity, and citation text.",
    )


def apply_contextual_adjustments(score: EvidenceScore, *, is_self_citation: bool) -> EvidenceScore:
    if not is_self_citation:
        return score

    adjusted_score = max(0.0, round(score.score - 0.2, 4))
    return EvidenceScore(
        score=adjusted_score,
        evidence_strength=strength_for_score(adjusted_score),
        rationale=f"{score.rationale} Self-citation context applies a deterministic downrank.",
    )

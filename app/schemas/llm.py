"""Schemas for normalized LLM citation analysis."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


EvidenceType = Literal[
    "first_or_seminal_claim",
    "detailed_comparison",
    "baseline_or_benchmark",
    "method_foundation",
    "theoretical_foundation",
    "application_extension",
    "positive_evaluation",
    "representative_work",
    "limitation_or_negative",
    "background",
    "adopted_or_combined",
    "state_of_the_art_claim",
    "important_author_citation",
    "long_context_citation",
    "precision_claim",
    "capability_recognition",
]


class LlmFinding(BaseModel):
    evidence_type: EvidenceType
    stance: Literal["positive", "neutral", "negative", "mixed"]
    mention_type: str
    citation_text: Optional[str] = None
    reasoning: str
    keywords: List[str] = Field(default_factory=list)
    keep: bool = True
    matched_template_ids: List[int] = Field(default_factory=list)
    template_match_reason: str = ""
    template_satisfied: Optional[bool] = None
    template_failure_reason: Optional[str] = None


class CitationAnalysisResult(BaseModel):
    findings: List[LlmFinding] = Field(default_factory=list)


class TemplateDirectEvidence(BaseModel):
    recommendation: Literal["include", "review", "exclude"]
    claim_type: Literal[
        "submm_precision_claim",
        "capability_recognition",
        "through_wall_eavesdropping",
        "rfid_loudspeaker_vibration",
        "method_use",
        "performance_comparison",
        "custom_template_evidence",
        "method_summary",
        "capability_summary",
        "method_foundation",
        "theoretical_foundation",
        "first_or_seminal_claim",
        "detailed_comparison",
        "baseline_or_benchmark",
        "positive_evaluation",
        "limitation_feedback",
        "ordinary_reference",
        "false_positive",
    ]
    evidence_quote: str
    evidence_context: str = ""
    reference_entry: str = ""
    why_this_judgment_zh: str
    copy_ready_zh: str
    confidence: Literal["high", "medium", "low"]
    matched_template_ids: List[int] = Field(default_factory=list)
    template_match_reason: str = ""
    template_satisfied: Optional[bool] = None
    template_failure_reason: Optional[str] = None
    mention_type: str = ""
    stance: str = ""
    surrounding_context: str = ""
    citation_markers: List[str] = Field(default_factory=list)
    claimed_target_marker: str = ""
    attribution_scope: str = ""
    grouped_or_single: str = ""
    semantic_relation: str = ""
    model_confidence: Optional[float] = None
    candidate_reason: str = ""
    grounding_status: Literal[
        "verified",
        "unresolved",
        "mismatch",
        "attribution_conflict",
    ] = "unresolved"
    evidence_strength: Literal["strong", "medium", "weak"] = "weak"
    template_relation: Literal[
        "explicit_positive_evaluation",
        "detailed_method_summary",
        "capability_recognition",
        "first_or_seminal_claim",
        "baseline_or_benchmark",
        "theoretical_foundation",
        "limitation_feedback",
        "unmatched",
    ] = "unmatched"


class TemplateDirectAnalysisResult(BaseModel):
    target_reference_marker: str = ""
    target_reference_entry: str = ""
    paper_level_summary_zh: str = ""
    evidences: List[TemplateDirectEvidence] = Field(default_factory=list)


class TemplateAdjudication(BaseModel):
    template_id: int
    satisfied: bool
    confidence: Literal["high", "medium", "low"]
    reason: str


class TemplateEvidenceAdjudicationResult(BaseModel):
    template_relation: Literal[
        "explicit_positive_evaluation",
        "detailed_method_summary",
        "capability_recognition",
        "first_or_seminal_claim",
        "baseline_or_benchmark",
        "theoretical_foundation",
        "limitation_feedback",
        "unmatched",
    ]
    adjudications: List[TemplateAdjudication] = Field(default_factory=list)
    why_this_judgment_zh: str = ""
    copy_ready_zh: str = ""


class LlmCitationAnalysisRequest(BaseModel):
    target_title: str
    candidate_spans: List[str] = Field(default_factory=list)
    template_prompt_fragments: List[str] = Field(default_factory=list)
    analysis_scope: str = "candidate_spans"
    citing_paper_title: Optional[str] = None
    cited_paper_title: Optional[str] = None
    cited_paper_year: Optional[int] = None
    cited_paper_venue: Optional[str] = None
    cited_paper_doi: Optional[str] = None
    cited_paper_authors: List[str] = Field(default_factory=list)
    full_text: Optional[str] = None
    prompt_text: Optional[str] = None


CitationAnalysisResponse = CitationAnalysisResult

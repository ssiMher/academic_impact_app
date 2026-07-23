"""Build deterministic prompts for the fake LLM provider."""

from typing import List, Optional

from app.analysis.candidate_spans import CandidateSpan
from app.analysis.citation_anchor import CitationAnchor, TargetReferenceContext


def build_citation_analysis_prompt(
    *,
    anchor: CitationAnchor,
    candidate_spans: List[CandidateSpan],
    template_prompt_fragments: Optional[List[str]] = None,
) -> str:
    span_lines = "\n".join(f"- {span.text}" for span in candidate_spans)
    template_lines = _format_template_prompt(template_prompt_fragments)
    return (
        "Analyze citation evidence for target paper:\n"
        f"TARGET_TITLE: {anchor.title}\n"
        "ACTIVE_EVIDENCE_TEMPLATES:\n"
        f"{template_lines}\n"
        "Prioritize template-related evidence, but every finding must include original citation_text.\n"
        "For each finding, include matched_template_ids, template_match_reason, template_satisfied, and template_failure_reason when applicable.\n"
        "Do not classify grouped citation or weak mention as strong evidence.\n"
        "CANDIDATE_SPANS:\n"
        f"{span_lines}\n"
    )


def build_fulltext_direct_prompt(
    *,
    citing_paper_title: str,
    cited_paper_title: str,
    cited_paper_year: Optional[int] = None,
    cited_paper_venue: Optional[str] = None,
    cited_paper_doi: Optional[str] = None,
    cited_paper_authors: Optional[List[str]] = None,
    target_reference_marker: Optional[str] = None,
    target_reference_entry: Optional[str] = None,
    full_text: str,
    template_prompt_fragments: Optional[List[str]] = None,
) -> str:
    template_lines = _format_template_prompt(template_prompt_fragments)
    author_line = ", ".join(cited_paper_authors or [])
    return (
        "You are analyzing the citing paper full text.\n"
        "Find whether and how this citing paper cites or discusses the cited paper.\n"
        "Only report evidence that is explicitly grounded in the provided full text.\n"
        "Each finding must include citation_text copied from the full text.\n"
        "If the full text only mentions similar keywords but does not clearly discuss the cited paper, return findings=[].\n"
        "Do not use bibliography/reference-list entries as findings.\n"
        "A reference entry only proves that the cited paper appears in References; it is not evidence of evaluation, use, comparison, or contribution.\n"
        "citation_text must come from the main body discussion, not from the References section.\n"
        "If the only occurrence of the cited paper is in References, return {\"findings\": []}.\n"
        "If a sentence discusses similar domain keywords generally but cannot be attributed to the cited paper, do not return it.\n"
        "Do not invent evidence.\n"
        "Do not infer praise without textual support.\n"
        "For grouped citations, only attribute a claim to the cited paper if the text clearly applies to it.\n"
        "If a grouped citation contains TARGET_REFERENCE_MARKER, the claim may be relevant to the cited paper as part of the group. Mark mention_type as grouped_citation and explain attribution uncertainty.\n"
        "Only output JSON.\n"
        "Do not output Markdown.\n"
        "Do not output explanatory prose.\n"
        "Do not output chain-of-thought or <think> content.\n"
        "The top-level JSON object must be {\"findings\": []}.\n"
        "If there is no evidence, return exactly {\"findings\": []}.\n"
        "Each finding must include citation_text copied from the full text, otherwise it will not be saved.\n"
        "Evaluate ACTIVE_EVIDENCE_TEMPLATES for every finding. Include matched_template_ids, template_match_reason, template_satisfied, and template_failure_reason.\n"
        "Return only JSON matching this exact schema:\n"
        "{\n"
        "  \"findings\": [\n"
        "    {\n"
        "      \"citation_text\": \"exact quote from the main body, not References\",\n"
        "      \"evidence_type\": \"method_foundation | theoretical_foundation | baseline_or_benchmark | detailed_comparison | positive_evaluation | representative_work | first_or_seminal_claim | application_extension | limitation_or_negative | background\",\n"
        "      \"stance\": \"positive | neutral | negative | mixed\",\n"
        "      \"mention_type\": \"explicit_target | grouped_citation | related_work | method_use | comparison | reference_only | other\",\n"
        "      \"reasoning\": \"why this quote is evidence for how the citing paper discusses the cited paper\",\n"
        "      \"highlight_keywords\": [\"...\"],\n"
        "      \"keep\": true,\n"
        "      \"matched_template_ids\": [1],\n"
        "      \"template_match_reason\": \"why this quote satisfies an active template\",\n"
        "      \"template_satisfied\": true,\n"
        "      \"template_failure_reason\": null\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "\n"
        f"CITING_PAPER_TITLE: {citing_paper_title}\n"
        f"CITED_PAPER_TITLE: {cited_paper_title}\n"
        f"CITED_PAPER_YEAR: {cited_paper_year or ''}\n"
        f"CITED_PAPER_VENUE: {cited_paper_venue or ''}\n"
        f"CITED_PAPER_DOI: {cited_paper_doi or ''}\n"
        f"CITED_PAPER_AUTHORS: {author_line}\n"
        f"TARGET_REFERENCE_MARKER: {target_reference_marker or ''}\n"
        f"TARGET_REFERENCE_ENTRY: {target_reference_entry or ''}\n"
        "ACTIVE_EVIDENCE_TEMPLATES:\n"
        f"{template_lines}\n"
        "FULL_EXTRACTED_TEXT:\n"
        f"{full_text}\n"
    )


def build_fulltext_anchor_direct_prompt(
    *,
    citing_paper_title: str,
    cited_paper_title: str,
    cited_paper_year: Optional[int] = None,
    cited_paper_venue: Optional[str] = None,
    cited_paper_doi: Optional[str] = None,
    cited_paper_authors: Optional[List[str]] = None,
    target_reference_marker: Optional[str] = None,
    target_reference_entry: Optional[str] = None,
    target_reference_contexts: Optional[List[TargetReferenceContext]] = None,
    target_alias_contexts: Optional[List[TargetReferenceContext]] = None,
    full_text: str = "",
    template_prompt_fragments: Optional[List[str]] = None,
) -> str:
    template_lines = _format_template_prompt(template_prompt_fragments)
    author_line = ", ".join(cited_paper_authors or [])
    reference_context_lines = "\n".join(
        _format_target_context(index + 1, context)
        for index, context in enumerate(target_reference_contexts or [])
    )
    alias_context_lines = "\n".join(
        _format_target_context(index + 1, context)
        for index, context in enumerate(target_alias_contexts or [])
    )
    return (
        "You are analyzing the citing paper full text with target-reference anchoring.\n"
        "Please prioritize TARGET_REFERENCE_CONTEXTS. These contexts are body-text locations that contain the target reference marker.\n"
        "If正文中的理论推导、公式建模、模型假设、方法设计或实验比较明确引用 TARGET_REFERENCE_MARKER，即使没有直接出现目标论文标题，也可以作为 theoretical_foundation 或 method_foundation 证据。\n"
        "If citation_text contains TARGET_REFERENCE_MARKER, do not return findings=[] just because the cited paper title is absent.\n"
        "If context is in References, it cannot be evidence.\n"
        "If grouped citations contain TARGET_REFERENCE_MARKER, you may return mention_type=\"grouped_citation\" and must explain attribution uncertainty.\n"
        "If Related Work treats the cited paper as a representative example of a method category or technical line, and citation_text contains TARGET_REFERENCE_MARKER, you may return evidence_type=\"representative_work\" with neutral stance.\n"
        "If representative_work is not certain, you may keep evidence_type=\"background\" but explain in reasoning that it is representative or field-positioning evidence.\n"
        "If context is ordinary related work listing, you may classify it as background.\n"
        "If context involves equations, model assumptions, technical derivations, method design, or domain-specific terminology supplied in the context, prioritize theoretical_foundation or method_foundation when supported.\n"
        "Only report evidence explicitly grounded in the provided body text.\n"
        "Each finding must include citation_text copied from the main body.\n"
        "Do not use bibliography/reference-list entries as findings.\n"
        "Only output JSON.\n"
        "Do not output Markdown.\n"
        "Do not output explanatory prose.\n"
        "Do not output chain-of-thought or <think> content.\n"
        "The top-level JSON object must be {\"findings\": []}.\n"
        "If there is no evidence, return exactly {\"findings\": []}.\n"
        "Evaluate ACTIVE_EVIDENCE_TEMPLATES for every finding. Include matched_template_ids, template_match_reason, template_satisfied, and template_failure_reason. If a template is relevant but not satisfied, explain why.\n"
        "Return only JSON matching this exact schema:\n"
        "{\n"
        "  \"findings\": [\n"
        "    {\n"
        "      \"citation_text\": \"exact quote from the main body, not References\",\n"
        "      \"evidence_type\": \"method_foundation | theoretical_foundation | baseline_or_benchmark | detailed_comparison | positive_evaluation | representative_work | first_or_seminal_claim | application_extension | limitation_or_negative | background\",\n"
        "      \"stance\": \"positive | neutral | negative | mixed\",\n"
        "      \"mention_type\": \"explicit_target | grouped_citation | related_work | method_use | comparison | reference_only | other\",\n"
        "      \"reasoning\": \"why this quote is evidence for how the citing paper discusses the cited paper\",\n"
        "      \"highlight_keywords\": [\"...\"],\n"
        "      \"keep\": true,\n"
        "      \"matched_template_ids\": [1],\n"
        "      \"template_match_reason\": \"why this quote satisfies an active template\",\n"
        "      \"template_satisfied\": true,\n"
        "      \"template_failure_reason\": null\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "\n"
        f"CITING_PAPER_TITLE: {citing_paper_title}\n"
        f"CITED_PAPER_TITLE: {cited_paper_title}\n"
        f"CITED_PAPER_YEAR: {cited_paper_year or ''}\n"
        f"CITED_PAPER_VENUE: {cited_paper_venue or ''}\n"
        f"CITED_PAPER_DOI: {cited_paper_doi or ''}\n"
        f"CITED_PAPER_AUTHORS: {author_line}\n"
        f"TARGET_REFERENCE_MARKER: {target_reference_marker or ''}\n"
        f"TARGET_REFERENCE_ENTRY: {target_reference_entry or ''}\n"
        "TARGET_REFERENCE_CONTEXTS:\n"
        f"{reference_context_lines or '(none)'}\n"
        "TARGET_ALIAS_CONTEXTS:\n"
        f"{alias_context_lines or '(none)'}\n"
        "ACTIVE_EVIDENCE_TEMPLATES:\n"
        f"{template_lines}\n"
        "FULL_EXTRACTED_TEXT:\n"
        f"{full_text}\n"
    )


def build_fulltext_template_direct_prompt(
    *,
    citing_paper_title: str,
    cited_paper_title: str,
    cited_paper_year: Optional[int] = None,
    cited_paper_venue: Optional[str] = None,
    cited_paper_doi: Optional[str] = None,
    cited_paper_authors: Optional[List[str]] = None,
    full_text: str,
    template_prompt_fragments: Optional[List[str]] = None,
) -> str:
    template_lines = _format_template_prompt(template_prompt_fragments)
    author_line = ", ".join(cited_paper_authors or [])
    return (
        "You are performing fulltext_template_direct report analysis.\n"
        "Read the complete citing paper full text. Do not rely on keyword hits alone.\n"
        "Find the cited paper in the References section. Identify TARGET_REFERENCE_MARKER and TARGET_REFERENCE_ENTRY.\n"
        "Find all body-text locations that cite TARGET_REFERENCE_MARKER.\n"
        "Evaluate every active user-defined template using its natural-language goal, configured concepts, required patterns, exclusion terms, and strict rules. Keywords are candidate signals only, not sufficient proof.\n"
        "Do not attribute any template concept to the cited paper unless the body evidence clearly anchors that concept to TARGET_REFERENCE_MARKER, the cited paper title, or the cited paper method name.\n"
        "Strong reference alignment rules:\n"
        "- Every evidence_quote must be a body-text quote, not a References entry.\n"
        "- The citation marker in evidence_quote must be TARGET_REFERENCE_MARKER. If the quote cites another marker, set recommendation=\"exclude\" and claim_type=\"false_positive\".\n"
        "- TARGET_REFERENCE_ENTRY must be the reference entry for the cited paper and must contain the cited paper title or DOI.\n"
        "- If the body quote uses [23] but [23] is a software project, dataset, hardware manual, or a different paper, exclude it as false_positive.\n"
        "- Do not use a target paper title that appears only in the References entry as body evidence.\n"
        "If first modifies another paper or method, recommendation must be exclude or review, not include.\n"
        "If sub-mm or millimeter-level does not clearly apply to the cited paper, do not write that the cited paper received third-party sub-mm recognition.\n"
        "If evidence is ordinary related work, classify it as ordinary_reference and set recommendation=\"review\" or \"exclude\", never \"include\".\n"
        "Grouped citations, table-only listings, title-only matches, reference-only entries, and ordinary related-work lists must not be recommendation=\"include\" unless the sentence separately describes the target paper.\n"
        "recommendation=\"include\" is allowed only for: direct sub-mm precision claims, through-wall eavesdropping capability, RFID loudspeaker/speaker vibration capability, concrete method use, concrete baseline/performance comparison. All other claims must be review or exclude.\n"
        "If evidence is negative or limitation feedback, classify it as limitation_feedback and do not make it a positive highlight.\n"
        "Deduplicate semantically identical evidence quotes. If one quote could fit multiple claim types, keep only the strongest claim type.\n"
        "Do not output prose outside JSON. Template evaluation metadata belongs only in the JSON fields defined below. Do not output Markdown.\n"
        "The JSON must be report-ready and match this schema exactly:\n"
        "{\n"
        "  \"target_reference_marker\": \"[23]\",\n"
        "  \"target_reference_entry\": \"full reference entry for the cited paper\",\n"
        "  \"paper_level_summary_zh\": \"brief Chinese summary of how this citing paper treats the cited paper\",\n"
        "  \"evidences\": [\n"
        "    {\n"
        "      \"recommendation\": \"include | review | exclude\",\n"
        "      \"claim_type\": \"submm_precision_claim | capability_recognition | through_wall_eavesdropping | rfid_loudspeaker_vibration | method_use | performance_comparison | limitation_feedback | ordinary_reference | false_positive\",\n"
        "      \"evidence_quote\": \"exact body-text quote, not References\",\n"
        "      \"evidence_context\": \"longer body context around the quote\",\n"
        "      \"reference_entry\": \"matching reference entry\",\n"
        "      \"why_this_judgment_zh\": \"why this quote supports this claim type; mention attribution risk if any\",\n"
        "      \"copy_ready_zh\": \"formal Chinese statement that can be copied into a report without overclaiming\",\n"
        "      \"confidence\": \"high | medium | low\",\n"
        "      \"matched_template_ids\": [1],\n"
        "      \"template_match_reason\": \"why the body evidence satisfies the configured template goal\",\n"
        "      \"template_satisfied\": true,\n"
        "      \"template_failure_reason\": \"why a relevant template was not satisfied, or empty\"\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "\n"
        "Template evaluation rules:\n"
        "- Apply each template's natural-language goal to the body quote and surrounding context, not to the References title alone.\n"
        "- A plain related-work listing does not satisfy a capability or evaluation template.\n"
        "- Respect each template's grouped-citation, target-marker, length, evidence-type, exclusion, and strict rules.\n"
        "- Misattributed or reference-mismatched claims must be false_positive or exclude.\n"
        "\n"
        f"CITING_PAPER_TITLE: {citing_paper_title}\n"
        f"CITED_PAPER_TITLE: {cited_paper_title}\n"
        f"CITED_PAPER_YEAR: {cited_paper_year or ''}\n"
        f"CITED_PAPER_VENUE: {cited_paper_venue or ''}\n"
        f"CITED_PAPER_DOI: {cited_paper_doi or ''}\n"
        f"CITED_PAPER_AUTHORS: {author_line}\n"
        "ACTIVE_EVIDENCE_TEMPLATES:\n"
        f"{template_lines}\n"
        "FULL_EXTRACTED_TEXT:\n"
        f"{full_text}\n"
    )


def build_fulltext_direct_repair_prompt(
    *,
    model_output: str,
    cited_paper_title: str,
) -> str:
    return (
        "Convert the following model output into the required CitationAnalysisResult JSON schema. "
        "Do not invent evidence. Do not add missing classifications unless they are supported by the quote. "
        "If a finding is only a reference-list entry or cannot be attributed to the cited paper, remove it. "
        "If no valid findings remain, return {\"findings\":[]}.\n"
        f"CITED_PAPER_TITLE: {cited_paper_title}\n"
        "REQUIRED_SCHEMA:\n"
        "{\"findings\":[{\"citation_text\":\"main body quote\",\"evidence_type\":\"method_foundation | theoretical_foundation | baseline_or_benchmark | detailed_comparison | positive_evaluation | representative_work | first_or_seminal_claim | application_extension | limitation_or_negative | background\",\"stance\":\"positive | neutral | negative | mixed\",\"mention_type\":\"explicit_target | grouped_citation | related_work | method_use | comparison | reference_only | other\",\"reasoning\":\"supported reason\",\"highlight_keywords\":[\"...\"],\"keep\":true}]}\n"
        "MODEL_OUTPUT:\n"
        f"{model_output}\n"
    )


def _format_target_context(index: int, context: TargetReferenceContext) -> str:
    return (
        f"[Context {index}] "
        f"section_heading={context.section_heading or 'unknown'}; "
        f"context_type={context.context_type}; "
        f"contains_formula={context.contains_formula}\n"
        f"{context.context_text}\n"
    )


def _format_template_prompt(template_prompt_fragments: Optional[List[str]]) -> str:
    fragments = [fragment for fragment in (template_prompt_fragments or []) if fragment]
    if not fragments:
        return "(none)"
    if len(fragments) == 1 and fragments[0].lstrip().startswith("["):
        return fragments[0]
    return "\n".join(f"- {fragment}" for fragment in fragments)

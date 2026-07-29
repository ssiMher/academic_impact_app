"""Post-process fulltext_template_direct report evidences.

The LLM owns the semantic reading, but the application still enforces the
minimum safety rules for report inclusion: target-reference alignment,
claim/recommendation consistency, and duplicate suppression.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.analysis.citation_anchor import (
    citation_text_has_target_anchor,
    match_bibliographic_identity,
)


CLAIM_PRIORITY = {
    "first_or_seminal_claim": 100,
    "detailed_comparison": 85,
    "baseline_or_benchmark": 75,
    "positive_evaluation": 65,
    "submm_precision_claim": 90,
    "through_wall_eavesdropping": 80,
    "rfid_loudspeaker_vibration": 70,
    "performance_comparison": 60,
    "custom_template_evidence": 55,
    "method_use": 50,
    "capability_recognition": 40,
    "method_summary": 35,
    "capability_summary": 35,
    "limitation_feedback": 30,
    "ordinary_reference": 20,
    "false_positive": 0,
}


def postprocess_template_direct_payload(
    payload: Dict[str, Any],
    *,
    citing_paper_title: str,
    cited_paper_title: str,
    cited_paper_doi: Optional[str] = None,
    target_reference_marker: str = "",
    target_reference_entry: str = "",
    reference_entries_by_marker: Optional[Dict[str, str]] = None,
    cited_paper_authors: Optional[List[str]] = None,
    cited_paper_year: Optional[int] = None,
    target_reference_resolved: bool = False,
) -> Dict[str, Any]:
    """Return a normalized template-direct payload suitable for reporting."""
    normalized = dict(payload or {})
    marker = _clean_marker(
        target_reference_marker or str(normalized.get("target_reference_marker") or "")
    )
    marker_text = f"[{marker}]" if marker else ""
    reference_entry = (
        target_reference_entry
        or str(normalized.get("target_reference_entry") or "")
    ).strip()
    normalized["target_reference_marker"] = marker_text or str(
        normalized.get("target_reference_marker") or ""
    )
    normalized["target_reference_entry"] = reference_entry

    normalized["evidences"] = normalize_direct_evidences_for_report(
        normalized.get("evidences", []),
        citing_paper_title=citing_paper_title,
        cited_paper_title=cited_paper_title,
        cited_paper_doi=cited_paper_doi,
        target_reference_marker=marker_text,
        target_reference_entry=reference_entry,
        reference_entries_by_marker=reference_entries_by_marker,
        cited_paper_authors=cited_paper_authors,
        cited_paper_year=cited_paper_year,
        target_reference_resolved=target_reference_resolved,
    )
    return normalized


def normalize_direct_evidences_for_report(
    evidences: Iterable[Dict[str, Any]],
    *,
    citing_paper_title: str,
    cited_paper_title: str,
    cited_paper_doi: Optional[str] = None,
    target_reference_marker: str = "",
    target_reference_entry: str = "",
    reference_entries_by_marker: Optional[Dict[str, str]] = None,
    cited_paper_authors: Optional[List[str]] = None,
    cited_paper_year: Optional[int] = None,
    target_reference_resolved: bool = False,
) -> List[Dict[str, Any]]:
    """Normalize direct evidences before persistence or report export."""
    marker = _clean_marker(target_reference_marker)
    marker_text = f"[{marker}]" if marker else ""
    normalized = [
        _normalize_evidence(
            evidence,
            cited_paper_title=cited_paper_title,
            cited_paper_doi=cited_paper_doi,
            target_marker=marker,
            target_marker_text=marker_text,
            target_reference_entry=target_reference_entry,
            reference_entries_by_marker=reference_entries_by_marker or {},
            cited_paper_authors=cited_paper_authors or [],
            cited_paper_year=cited_paper_year,
            target_reference_resolved=target_reference_resolved,
        )
        for evidence in evidences
        if isinstance(evidence, dict)
    ]
    return _deduplicate_evidences(
        normalized,
        citing_paper_title=citing_paper_title,
    )


def _normalize_evidence(
    evidence: Dict[str, Any],
    *,
    cited_paper_title: str,
    cited_paper_doi: Optional[str],
    target_marker: str,
    target_marker_text: str,
    target_reference_entry: str,
    reference_entries_by_marker: Dict[str, str],
    cited_paper_authors: List[str],
    cited_paper_year: Optional[int],
    target_reference_resolved: bool,
) -> Dict[str, Any]:
    item = dict(evidence)
    original_claim_type = str(
        item.get("original_claim_type")
        or item.get("claim_type")
        or "ordinary_reference"
    )
    original_recommendation = str(
        item.get("original_recommendation")
        or item.get("recommendation")
        or "review"
    )
    for generated_key in (
        "filter_reason",
        "postprocess_reason",
        "filter_reason_codes",
        "failure_reason_codes",
        "template_failure_reason_codes",
        "reference_alignment_reason_code",
        "reference_alignment_method",
        "reference_alignment_score",
    ):
        item.pop(generated_key, None)
    item["claim_type"] = original_claim_type
    item["recommendation"] = original_recommendation
    quote = str(item.get("evidence_quote") or "")
    context = str(item.get("evidence_context") or "")
    combined = f"{quote}\n{context}"
    claim_type = original_claim_type
    recommendation = original_recommendation
    item["original_recommendation"] = original_recommendation
    item["original_claim_type"] = original_claim_type
    evidence_marker = _evidence_marker_for_quote(
        quote,
        context,
        target_marker=target_marker,
    )
    resolved_marker_entry = reference_entries_by_marker.get(evidence_marker, "")
    evidence_reference_entry_raw = (
        resolved_marker_entry
        or str(item.get("evidence_reference_entry_raw") or "")
        or str(item.get("reference_entry") or "")
    ).strip()
    deterministic_entry = resolved_marker_entry or (
        target_reference_entry
        if target_reference_resolved and evidence_marker == target_marker
        else ""
    )
    entry_for_matching = deterministic_entry or evidence_reference_entry_raw
    quote_markers = _extract_reference_markers(quote)
    context_markers = _extract_reference_markers(context)
    quote_has_target_marker = bool(
        target_marker and citation_text_has_target_anchor(quote, target_marker)
    )
    inherited_anchor, inheritance_reason = _safe_context_anchor_inheritance(
        quote,
        context,
        target_marker,
    )
    has_effective_target_anchor = quote_has_target_marker or inherited_anchor
    identity_match = match_bibliographic_identity(
        entry_for_matching,
        target_title=cited_paper_title,
        target_doi=cited_paper_doi,
        target_reference_entry=target_reference_entry,
        target_authors=cited_paper_authors,
        target_year=cited_paper_year,
        resolver_marker_matched=bool(
            target_reference_resolved
            and target_marker
            and evidence_marker == target_marker
            and has_effective_target_anchor
            and resolved_marker_entry
        ),
    )
    entry_matches_target = identity_match.status == "matched"
    target_scope = _target_marker_scope(quote, context, target_marker)
    target_scope_markers = _extract_reference_markers(target_scope)
    quote_has_other_marker = bool(
        quote_has_target_marker
        and any(marker != target_marker for marker in target_scope_markers)
    )
    grouped_citation = quote_has_other_marker
    title_alias_in_quote = _contains_title_alias(quote, cited_paper_title)
    body_author = _body_author_for_marker(target_scope, target_marker)
    reference_author = _reference_first_author(evidence_reference_entry_raw)
    attribution_conflict = bool(
        body_author
        and reference_author
        and _normalize_author_name(body_author) != _normalize_author_name(reference_author)
    )

    reasons: List[str] = []
    reference_match_status = "unresolved"
    reference_match_reason = "reference_entry_unresolved"
    if deterministic_entry:
        if entry_matches_target:
            reference_match_status = "matched"
            reference_match_reason = identity_match.reason_code
        else:
            reference_match_status = "mismatch"
            reference_match_reason = identity_match.reason_code

    title_or_reference_only = _is_title_only_or_reference_only(quote, combined)

    if target_marker and evidence_marker and evidence_marker != target_marker and not quote_has_target_marker:
        item = _exclude(item, reason="cited_other_reference_marker")
        reference_match_status = "mismatch"
        reference_match_reason = "evidence_marker_not_target_marker"
    elif deterministic_entry and not entry_matches_target:
        item = _exclude(item, reason="reference_entry_target_mismatch")
    elif not deterministic_entry and target_marker and recommendation == "include":
        item["recommendation"] = "review"
        item["confidence"] = _lower_confidence(item.get("confidence"))
        reasons.append("reference_entry_unresolved")
    elif target_marker and quote_markers and not quote_has_target_marker:
        item = _exclude(item, reason="cited_other_reference_marker")
    elif target_marker and not has_effective_target_anchor and not title_alias_in_quote:
        item = _exclude(item, reason="target_anchor_missing")
    elif _looks_like_reference_entry(quote):
        item = _exclude(item, reason="reference_only")
    else:
        if title_or_reference_only:
            item["recommendation"] = "exclude"
            reasons.append("title_or_reference_only_not_include")
        if recommendation == "include":
            downgrade_reason = _include_structural_downgrade_reason(
                quote=quote,
                combined=combined,
                has_target_marker=has_effective_target_anchor,
                reference_match_status=reference_match_status,
            )
            if downgrade_reason:
                item["recommendation"] = "review"
                item["confidence"] = _lower_confidence(item.get("confidence"))
                reasons.append(downgrade_reason)
        if claim_type == "ordinary_reference" and item.get("recommendation") == "include":
            item["recommendation"] = "review"
            item["confidence"] = _lower_confidence(item.get("confidence"))
            reasons.append("ordinary_reference_not_include")

    if attribution_conflict and item.get("recommendation") != "exclude":
        item["recommendation"] = "review"
        item["confidence"] = _lower_confidence(item.get("confidence"))
        reasons.append("reference_attribution_conflict")

    if (
        original_recommendation == "exclude"
        and item.get("recommendation") == "exclude"
        and item.get("claim_type") in {"method_summary", "capability_summary"}
        and reference_match_status == "matched"
        and has_effective_target_anchor
        and not title_or_reference_only
        and not attribution_conflict
    ):
        # The model recommendation is provisional in template-direct mode.
        # Preserve a safely aligned factual summary for deterministic template
        # evaluation instead of discarding it before active templates run.
        item["recommendation"] = "review"
        item["confidence"] = _lower_confidence(item.get("confidence"))
        reasons.append("candidate_requires_matching_template")

    item["final_recommendation"] = str(item.get("recommendation") or "review")
    item["final_claim_type"] = str(item.get("claim_type") or claim_type)
    item["target_reference_marker"] = target_marker_text
    item["resolved_target_marker"] = target_marker_text
    item["evidence_reference_marker"] = f"[{evidence_marker}]" if evidence_marker else target_marker_text
    item["evidence_reference_entry_raw"] = evidence_reference_entry_raw
    item["reference_match_status"] = reference_match_status
    item["reference_match_reason"] = reference_match_reason
    item["reference_alignment_status"] = reference_match_status
    item["reference_alignment_reason_code"] = reference_match_reason
    item["reference_alignment_method"] = identity_match.method
    item["reference_alignment_score"] = identity_match.score
    item["normalized_target_reference"] = target_reference_entry
    item["citation_text_contains_target_marker"] = quote_has_target_marker
    item["target_anchor_inherited"] = inherited_anchor
    item["target_anchor_inheritance_reason"] = inheritance_reason
    item["target_anchor_status"] = (
        "direct_marker"
        if quote_has_target_marker
        else "inherited_named_method"
        if inherited_anchor
        else "missing"
    )
    item["quote_marker_list"] = _sorted_markers(quote_markers)
    item["context_marker_list"] = _sorted_markers(context_markers)
    item["citation_text_contains_other_marker"] = quote_has_other_marker
    item["target_reference_entry_matches_target"] = entry_matches_target
    item["reference_attribution_conflict"] = attribution_conflict
    item["reference_attribution_body_author"] = body_author
    item["reference_attribution_entry_author"] = reference_author
    item["reference_attribution_reason"] = (
        "body_author_reference_author_mismatch" if attribution_conflict else ""
    )
    grounding_status = _grounding_status(
        reference_match_status=reference_match_status,
        has_effective_target_anchor=has_effective_target_anchor,
        title_or_reference_only=title_or_reference_only,
        attribution_conflict=attribution_conflict,
        final_claim_type=str(item.get("claim_type") or claim_type),
    )
    template_relation = _template_relation_for_evidence(item)
    item["grounding_status"] = grounding_status
    item["evidence_strength"] = _evidence_strength(
        grounding_status=grounding_status,
        template_relation=template_relation,
        claim_type=str(item.get("claim_type") or claim_type),
    )
    item["template_relation"] = template_relation
    if grouped_citation:
        item["grouped_citation"] = True
    else:
        item["grouped_citation"] = False
    if reasons:
        item["postprocess_reason"] = "; ".join(reasons)
        _append_reason(item, reasons[-1])
    reason_codes = direct_evidence_failure_reason_codes(item)
    item["filter_reason_codes"] = reason_codes
    item["failure_reason_codes"] = reason_codes
    return item


def _grounding_status(
    *,
    reference_match_status: str,
    has_effective_target_anchor: bool,
    title_or_reference_only: bool,
    attribution_conflict: bool,
    final_claim_type: str,
) -> str:
    if attribution_conflict:
        return "attribution_conflict"
    if reference_match_status == "mismatch" or final_claim_type == "false_positive":
        return "mismatch"
    if (
        reference_match_status == "matched"
        and has_effective_target_anchor
        and not title_or_reference_only
    ):
        return "verified"
    return "unresolved"


def _template_relation_for_evidence(evidence: Dict[str, Any]) -> str:
    claim_type = str(
        evidence.get("final_claim_type")
        or evidence.get("claim_type")
        or ""
    )
    semantic_relation = str(evidence.get("semantic_relation") or "").lower()
    if claim_type == "positive_evaluation":
        return "explicit_positive_evaluation"
    if claim_type in {"method_summary", "method_use", "method_foundation"}:
        return "detailed_method_summary"
    if claim_type in {
        "capability_summary",
        "capability_recognition",
        "through_wall_eavesdropping",
        "rfid_loudspeaker_vibration",
    }:
        return "capability_recognition"
    if claim_type == "first_or_seminal_claim":
        return "first_or_seminal_claim"
    if claim_type in {"baseline_or_benchmark", "performance_comparison"}:
        return "baseline_or_benchmark"
    if claim_type in {"theoretical_foundation", "detailed_comparison"}:
        return (
            "theoretical_foundation"
            if claim_type == "theoretical_foundation"
            else "detailed_method_summary"
        )
    if claim_type in {"limitation_feedback", "limitation_or_negative"}:
        return "limitation_feedback"
    if "method" in semantic_relation:
        return "detailed_method_summary"
    if "capability" in semantic_relation:
        return "capability_recognition"
    return "unmatched"


def _evidence_strength(
    *,
    grounding_status: str,
    template_relation: str,
    claim_type: str,
) -> str:
    if grounding_status in {"mismatch", "attribution_conflict"}:
        return "weak"
    substantive = template_relation != "unmatched" and claim_type not in {
        "ordinary_reference",
        "false_positive",
    }
    if grounding_status == "verified" and substantive:
        return "strong"
    if grounding_status == "verified" or substantive:
        return "medium"
    return "weak"


def _include_structural_downgrade_reason(
    *,
    quote: str,
    combined: str,
    has_target_marker: bool,
    reference_match_status: str,
) -> str:
    if reference_match_status != "matched":
        return "reference_match_not_matched"
    if _is_title_only_or_reference_only(quote, combined):
        return "title_or_reference_only_not_include"
    if not has_target_marker:
        return "include_requires_body_target_marker"
    return ""


def _deduplicate_evidences(
    evidences: Iterable[Dict[str, Any]],
    *,
    citing_paper_title: str,
) -> List[Dict[str, Any]]:
    kept: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str, str]] = []
    for evidence in evidences:
        key = (
            _normalize(citing_paper_title),
            str(evidence.get("evidence_reference_marker") or evidence.get("target_reference_marker") or ""),
            _normalize_quote(str(evidence.get("evidence_quote") or "")),
        )
        if key not in kept:
            kept[key] = evidence
            order.append(key)
            continue
        current = kept[key]
        if _evidence_rank(evidence) > _evidence_rank(current):
            replacement = dict(evidence)
            replacement["postprocess_reason"] = _join_reason(
                replacement.get("postprocess_reason"),
                "deduplicated_kept_strongest_claim_type",
            )
            kept[key] = replacement
        else:
            current["postprocess_reason"] = _join_reason(
                current.get("postprocess_reason"),
                "deduplicated_kept_strongest_claim_type",
            )
    return [kept[key] for key in order]


def _evidence_marker_for_quote(
    quote: str,
    context: str,
    *,
    target_marker: str,
) -> str:
    quote_markers = _extract_reference_markers(quote)
    if target_marker and target_marker in quote_markers:
        return target_marker
    if quote_markers:
        return _lowest_marker(quote_markers)
    context_markers = _extract_reference_markers(context)
    if target_marker and target_marker in context_markers:
        return target_marker
    if context_markers:
        return _lowest_marker(context_markers)
    return target_marker or ""


def _lowest_marker(markers: Iterable[str]) -> str:
    values = []
    for marker in markers:
        try:
            values.append(int(marker))
        except ValueError:
            continue
    return str(min(values)) if values else ""


def _sorted_markers(markers: Iterable[str]) -> List[str]:
    return sorted(
        {str(marker) for marker in markers if str(marker).isdigit()},
        key=int,
    )


def _safe_context_anchor_inheritance(
    quote: str,
    context: str,
    target_marker: str,
) -> Tuple[bool, str]:
    """Allow a named method to inherit a same-paragraph target marker."""
    if not quote.strip() or not context.strip() or not target_marker:
        return False, ""
    if citation_text_has_target_anchor(quote, target_marker):
        return False, ""
    if _extract_reference_markers(quote):
        return False, "quote_contains_other_reference_marker"

    quote_start = context.find(quote)
    if quote_start < 0:
        return False, "quote_not_located_in_context"
    prefix = context[:quote_start]
    marker_matches = list(
        re.finditer(
            rf"\[\s*{re.escape(target_marker)}\s*\]",
            prefix,
        )
    )
    if not marker_matches:
        return False, "target_marker_not_before_quote"

    marker_start = marker_matches[-1].start()
    inheritance_scope = context[marker_start:quote_start]
    if re.search(r"\n\s*\n", inheritance_scope):
        return False, "target_marker_in_different_paragraph"
    scope_markers = _extract_reference_markers(inheritance_scope)
    if any(marker != target_marker for marker in scope_markers):
        return False, "other_reference_marker_between_anchor_and_quote"

    method_names = _introduced_method_names(inheritance_scope)
    normalized_quote = _normalize(quote)
    for method_name in method_names:
        if _normalize(method_name) in normalized_quote:
            return True, f"same_paragraph_named_method:{method_name}"
    return False, "no_unique_named_method_link"


def _introduced_method_names(text: str) -> List[str]:
    names: List[str] = []
    patterns = (
        r"\b(?:called|named)\s+([A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)\b",
        r"\b([A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)\s+"
        r"(?:is|was)\s+(?:proposed|introduced|developed|presented)\b",
    )
    for pattern in patterns:
        names.extend(re.findall(pattern, text or ""))
    return list(dict.fromkeys(names))


def _evidence_rank(evidence: Dict[str, Any]) -> Tuple[int, int]:
    recommendation_rank = {"include": 3, "review": 2, "exclude": 1}.get(
        str(evidence.get("recommendation") or ""), 0
    )
    claim_rank = CLAIM_PRIORITY.get(str(evidence.get("claim_type") or ""), 0)
    return (recommendation_rank, claim_rank)


def _exclude(item: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    updated = dict(item)
    updated["recommendation"] = "exclude"
    updated["claim_type"] = "false_positive"
    updated["confidence"] = "high"
    updated["postprocess_reason"] = _join_reason(updated.get("postprocess_reason"), reason)
    _append_reason(updated, reason)
    return updated


def _append_reason(item: Dict[str, Any], reason: str) -> None:
    reason_zh = {
        "reference_entry_target_mismatch": "引用编号对应的参考文献条目与目标论文标题或 DOI 不匹配。",
        "cited_other_reference_marker": "原文证据句引用了其他编号，没有引用目标论文编号。",
        "target_anchor_missing": "原文证据句缺少目标引用编号或目标题名锚点。",
        "reference_only": "该证据看起来是参考文献条目，不是正文证据。",
        "reference_entry_unresolved": "无法从引用论文 References 中解析该编号对应的原始条目，不能推荐纳入。",
        "reference_match_not_matched": "该证据编号对应的参考文献条目未确认匹配目标论文。",
        "ordinary_reference_not_include": "普通相关工作不能作为推荐纳入强证据。",
        "include_claim_type_not_strong": "该 claim_type 不属于允许推荐纳入的强证据类型。",
        "include_requires_body_target_marker": "推荐纳入要求正文证据句直接包含目标引用编号。",
        "reason_text_indicates_weak_evidence": "模型理由或表述承认该证据只是普通引用、列举、标题项或存在归因风险。",
        "title_or_reference_only_not_include": "证据仅来自题名、参考文献条目或标题列举，不是正文第三方评价。",
        "submm_claim_missing_body_submm_term": "正文证据句没有明确 sub-mm / millimeter-level 表达。",
        "submm_claim_missing_body_capability_term": "正文只是题名或相关工作列举，没有说明目标论文实现亚毫米能力。",
        "through_wall_claim_missing_body_term": "正文证据缺少 through-wall/eavesdropping 能力表述。",
        "rfid_loudspeaker_claim_missing_body_terms": "正文证据缺少 RFID loudspeaker/speaker vibration 能力表述。",
        "performance_comparison_missing_concrete_terms": "正文证据缺少具体比较或性能指标表述。",
        "method_use_missing_concrete_terms": "正文证据缺少明确方法使用表述。",
        "capability_recognition_missing_concrete_terms": "正文证据缺少明确能力确认表述。",
        "limitation_language_not_include": "原文或评价理由包含局限性/实用性不足表述，不能作为推荐纳入的正向强证据。",
        "generic_rfid_eavesdropping_not_include": "正文只是 RFID/eavesdropping 普通描述，缺少亚毫米、穿墙、扬声器振动或具体方法/性能佐证。",
        "reference_attribution_conflict": "正文引用处的作者归因与该编号参考文献的首位作者不一致，需要人工核对。",
        "first_claim_scope_not_targeted": "首次/开创性表达没有明确修饰目标论文。",
        "detailed_comparison_insufficient_detail": "对比表述过短或缺少具体方法、指标或实验细节。",
        "baseline_or_benchmark_not_experimental": "未明确将目标论文作为实验 baseline/benchmark 使用。",
        "positive_evaluation_not_explicit": "正文没有对目标论文给出明确正向评价。",
    }.get(reason, reason)
    existing = str(item.get("why_this_judgment_zh") or "").strip()
    if reason_zh and reason_zh not in existing:
        item["why_this_judgment_zh"] = (existing + " " + reason_zh).strip()


def direct_evidence_failure_reason_codes(evidence: Dict[str, Any]) -> List[str]:
    """Map free-text diagnostics to stable run/report reason codes."""
    codes: List[str] = []
    for key in (
        "filter_reason_codes",
        "failure_reason_codes",
        "template_failure_reason_codes",
    ):
        for value in evidence.get(key, []) or []:
            normalized = str(value or "").strip()
            if normalized and normalized not in codes:
                codes.append(normalized)
    text = " ".join(
        [
            str(evidence.get("postprocess_reason") or ""),
            str(evidence.get("template_failure_reason") or ""),
            " ".join(
                str(item.get("template_failure_reason") or "")
                for item in evidence.get("template_evaluations", []) or []
                if isinstance(item, dict)
            ),
        ]
    ).casefold()

    def add(code: str) -> None:
        if code not in codes:
            codes.append(code)

    reference_status = str(evidence.get("reference_match_status") or "")
    if (
        reference_status == "mismatch"
        or (
            not reference_status
            and "reference mismatch" in text
        )
    ):
        add("reference_mismatch")
    has_anchor_diagnostics = (
        "citation_text_contains_target_marker" in evidence
        or "target_anchor_inherited" in evidence
    )
    if (
        has_anchor_diagnostics
        and not evidence.get("citation_text_contains_target_marker", False)
        and not evidence.get("target_anchor_inherited", False)
    ) or (
        not has_anchor_diagnostics
        and (
            "does not anchor to target paper" in text
            or "target_anchor_missing" in text
        )
    ):
        add("target_marker_missing")
    if "evidence type" in text and "not allowed" in text:
        add("evidence_type_not_allowed")
    if "candidate_requires_matching_template" in text:
        add("candidate_requires_matching_template")
    if evidence.get("template_match_level") == "candidate":
        add("template_candidate_requires_review")
    if "no explicit first/pioneering" in text:
        add("no_first_or_pioneering_expression")
    if "no required evidence pattern" in text:
        add("template_required_pattern_missing")
    final_claim_type = (
        evidence.get("final_claim_type")
        or evidence.get("claim_type")
    )
    if "ordinary_reference" == final_claim_type or "ordinary reference" in text:
        add("ordinary_reference")
    matched_template_types = {
        str(value)
        for value in evidence.get("matched_template_types", []) or []
    }
    negative_template_satisfied = (
        "limitation_or_negative" in matched_template_types
        or any(
            isinstance(evaluation, dict)
            and evaluation.get("template_type") == "limitation_or_negative"
            and evaluation.get("template_satisfied") is True
            for evaluation in evidence.get("template_evaluations", []) or []
        )
    )
    if negative_template_satisfied:
        codes = [
            code
            for code in codes
            if code != "limitation_feedback_not_positive"
        ]
    if (
        final_claim_type == "limitation_feedback"
        and not negative_template_satisfied
    ) or (
        "limitation feedback" in text
        and not negative_template_satisfied
    ):
        add("limitation_feedback_not_positive")
    if "title-only" in text or "reference-only" in text or "reference_only" in text:
        add("reference_only")
    if evidence.get("original_recommendation") == "exclude":
        add("llm_recommended_exclude")
    if (
        evidence.get("template_satisfied") is False
        and evidence.get("template_evaluations")
        and not codes
    ):
        add("template_goal_not_satisfied")
    if evidence.get("final_recommendation") in {"review", "exclude"} and not codes:
        add("template_goal_not_satisfied")
    return codes


def _contains_title_alias(text: str, cited_paper_title: str) -> bool:
    normalized_text = _normalize(text)
    normalized_title = _normalize(cited_paper_title)
    if normalized_title and normalized_title in normalized_text:
        return True
    if ":" in cited_paper_title:
        short = _normalize(cited_paper_title.split(":", 1)[0])
        if short and len(short) >= 6 and short in normalized_text:
            return True
    return False


def _extract_reference_markers(text: str) -> set[str]:
    markers: set[str] = set()
    for start, end in re.findall(r"\[(\d+)\]\s*[-–—]\s*\[(\d+)\]", text or ""):
        low, high = sorted((int(start), int(end)))
        markers.update(str(value) for value in range(low, high + 1))
    for content in re.findall(r"\[([^\]]+)\]", text or ""):
        normalized = content.replace("–", "-").replace("—", "-")
        for token in re.split(r"\s*,\s*", normalized):
            token = token.strip()
            if "-" in token:
                left, right = [part.strip() for part in token.split("-", 1)]
                if left.isdigit() and right.isdigit():
                    low, high = sorted((int(left), int(right)))
                    markers.update(str(value) for value in range(low, high + 1))
            elif token.isdigit():
                markers.add(token)
    return markers


def _target_marker_scope(quote: str, context: str, target_marker: str) -> str:
    """Return only the sentence or clause that contains the target marker."""
    if not target_marker:
        return quote
    for text in (quote, context):
        for sentence in _split_sentences(text):
            if citation_text_has_target_anchor(sentence, target_marker):
                return sentence.strip()
    return quote


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    return [
        part
        for part in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", text)
        if part and part.strip()
    ]


def _body_author_for_marker(text: str, target_marker: str) -> str:
    if not text or not target_marker:
        return ""
    marker_pattern = re.escape(f"[{target_marker}]")
    matches = list(
        re.finditer(
            rf"\b([A-Z][A-Za-z'’-]+)(?:\s+et\s+al\.?)?\s*{marker_pattern}",
            text,
        )
    )
    if not matches:
        return ""
    candidate = matches[-1].group(1)
    if candidate.isupper() or candidate.lower() in {
        "figure",
        "method",
        "paper",
        "reference",
        "section",
        "system",
        "table",
        "work",
    }:
        return ""
    return candidate


def _reference_first_author(reference_entry: str) -> str:
    if not reference_entry:
        return ""
    text = re.sub(r"^\s*\[\d+\]\s*", "", reference_entry).strip()
    prefix = re.split(r",|\bet\s+al\.?", text, maxsplit=1, flags=re.I)[0]
    tokens = re.findall(r"\b(?:[A-Z]\.|[A-Z][A-Za-z'’-]+)\b", prefix)
    names = [token.rstrip(".") for token in tokens if len(token.rstrip(".")) > 1]
    return names[-1] if names else ""


def _normalize_author_name(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.casefold())


def _clean_marker(marker: str) -> str:
    value = str(marker or "").strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    return value


def _looks_like_reference_entry(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    has_pages_or_venue = bool(re.search(r"\b(proc|conference|journal|vol|pp|doi|arxiv|isbn)\b", normalized))
    has_year = bool(re.search(r"\b(19|20)\d{2}\b", normalized))
    starts_with_marker = bool(re.match(r"^\s*\[\d+\]", text or ""))
    return starts_with_marker and has_year and has_pages_or_venue


def _is_title_only_or_reference_only(quote: str, combined: str) -> bool:
    normalized_quote = _normalize(quote)
    normalized_combined = _normalize(combined)
    if not normalized_quote:
        return True
    if _looks_like_reference_entry(quote):
        return True
    weak_patterns = (
        "reference is the target paper title",
        "target paper title",
        "paper title",
        "listed as a related work",
        "appears in related work",
        "is listed as related work",
    )
    if any(pattern in normalized_combined for pattern in weak_patterns):
        return True
    without_markers = re.sub(r"\[[^\]]+\]", "", quote).strip()
    token_count = len(_meaningful_tokens(_normalize(without_markers)))
    return token_count <= 3


def _lower_confidence(value: Any) -> str:
    return "low" if str(value or "").lower() == "low" else "medium"


def _join_reason(existing: Any, reason: str) -> str:
    parts = [part.strip() for part in str(existing or "").split(";") if part.strip()]
    if reason not in parts:
        parts.append(reason)
    return "; ".join(parts)


def _normalize_quote(text: str) -> str:
    return re.sub(r"\s+", " ", _normalize(text)).strip()


def _meaningful_tokens(text: str) -> List[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "the",
        "of",
        "to",
        "for",
        "in",
        "on",
        "with",
        "based",
        "using",
        "towards",
        "toward",
    }
    return [token for token in re.findall(r"[a-z0-9]+", text) if token not in stopwords and len(token) > 1]


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("’", "'").replace("“", '"').replace("”", '"')
    value = re.sub(r"[^a-zA-Z0-9./\-\s]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()

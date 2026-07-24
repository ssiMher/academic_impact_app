"""Post-process fulltext_template_direct report evidences.

The LLM owns the semantic reading, but the application still enforces the
minimum safety rules for report inclusion: target-reference alignment,
claim/recommendation consistency, and duplicate suppression.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.analysis.citation_anchor import citation_text_has_target_anchor


INCLUDE_CLAIM_TYPES = {
    "submm_precision_claim",
    "capability_recognition",
    "through_wall_eavesdropping",
    "rfid_loudspeaker_vibration",
    "method_use",
    "performance_comparison",
    "custom_template_evidence",
}

CLAIM_PRIORITY = {
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
) -> Dict[str, Any]:
    item = dict(evidence)
    quote = str(item.get("evidence_quote") or "")
    context = str(item.get("evidence_context") or "")
    combined = f"{quote}\n{context}"
    claim_type = str(item.get("claim_type") or "ordinary_reference")
    recommendation = str(item.get("recommendation") or "review")
    reason_text = (
        str(item.get("why_this_judgment_zh") or "")
        + "\n"
        + str(item.get("copy_ready_zh") or "")
    )

    evidence_marker = _evidence_marker_for_quote(
        quote,
        context,
        target_marker=target_marker,
    )
    evidence_reference_entry_raw = (
        reference_entries_by_marker.get(evidence_marker)
        or str(item.get("evidence_reference_entry_raw") or "")
    ).strip()
    entry_for_matching = evidence_reference_entry_raw or target_reference_entry
    entry_matches_target = _reference_entry_matches_target(
        entry_for_matching,
        cited_paper_title=cited_paper_title,
        cited_paper_doi=cited_paper_doi,
    )
    target_scope = _target_marker_scope(quote, context, target_marker)
    quote_markers = _extract_reference_markers(target_scope)
    quote_has_target_marker = bool(
        target_marker and citation_text_has_target_anchor(target_scope, target_marker)
    )
    quote_has_other_marker = bool(
        target_marker and quote_markers and any(marker != target_marker for marker in quote_markers)
    )
    grouped_citation = quote_has_target_marker and quote_has_other_marker
    title_alias_in_quote = _contains_title_alias(quote, cited_paper_title)
    limitation_reason = _limitation_downgrade_reason(f"{combined}\n{reason_text}")
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
    if evidence_reference_entry_raw:
        if entry_matches_target:
            reference_match_status = "matched"
            reference_match_reason = "reference_entry_matches_target"
        else:
            reference_match_status = "mismatch"
            reference_match_reason = "reference_entry_target_mismatch"

    inferred_claim_type = _infer_stronger_claim_type(
        claim_type=claim_type,
        quote=quote,
        combined=combined,
        reason_text=reason_text,
        has_target_marker=quote_has_target_marker,
        reference_match_status=reference_match_status,
        grouped_citation=grouped_citation,
        limitation_reason=limitation_reason,
    )
    if inferred_claim_type != claim_type:
        claim_type = inferred_claim_type
        item["claim_type"] = inferred_claim_type
    if claim_type == "ordinary_reference":
        summary_claim_type = _infer_summary_claim_type(target_scope)
        if summary_claim_type:
            claim_type = summary_claim_type
            item["claim_type"] = summary_claim_type
    title_or_reference_only = _is_title_only_or_reference_only(quote, combined)

    if target_marker and evidence_marker and evidence_marker != target_marker and not quote_has_target_marker:
        item = _exclude(item, reason="cited_other_reference_marker")
        reference_match_status = "mismatch"
        reference_match_reason = "evidence_marker_not_target_marker"
    elif evidence_reference_entry_raw and not entry_matches_target:
        item = _exclude(item, reason="reference_entry_target_mismatch")
    elif not evidence_reference_entry_raw and target_marker and recommendation == "include":
        item["recommendation"] = "review"
        item["confidence"] = _lower_confidence(item.get("confidence"))
        reasons.append("reference_entry_unresolved")
    elif target_marker and quote_markers and not quote_has_target_marker:
        item = _exclude(item, reason="cited_other_reference_marker")
    elif target_marker and not quote_has_target_marker and not title_alias_in_quote:
        item = _exclude(item, reason="target_anchor_missing")
    elif _looks_like_reference_entry(quote):
        item = _exclude(item, reason="reference_only")
    else:
        if title_or_reference_only and claim_type == "submm_precision_claim":
            item["recommendation"] = "review"
            item["claim_type"] = "ordinary_reference"
            claim_type = "ordinary_reference"
            reasons.append("title_or_reference_only_not_include")
        if recommendation == "include":
            downgrade_reason = limitation_reason or _include_downgrade_reason(
                    claim_type=claim_type,
                    quote=quote,
                    combined=combined,
                    has_target_marker=quote_has_target_marker,
                    grouped_citation=grouped_citation,
                    title_alias_in_quote=title_alias_in_quote,
                    reference_match_status=reference_match_status,
                    reason_text=reason_text,
                )
            if downgrade_reason:
                item["recommendation"] = "review"
                item["confidence"] = _lower_confidence(item.get("confidence"))
                reasons.append(downgrade_reason)
                if downgrade_reason.startswith("limitation_"):
                    item["claim_type"] = "limitation_feedback"
                    claim_type = "limitation_feedback"
                elif downgrade_reason == "title_or_reference_only_not_include":
                    item["claim_type"] = "ordinary_reference"
                    claim_type = "ordinary_reference"
        if claim_type == "ordinary_reference" and item.get("recommendation") == "include":
            item["recommendation"] = "review"
            item["confidence"] = _lower_confidence(item.get("confidence"))
            reasons.append("ordinary_reference_not_include")

    if attribution_conflict and item.get("recommendation") != "exclude":
        item["recommendation"] = "review"
        item["confidence"] = _lower_confidence(item.get("confidence"))
        reasons.append("reference_attribution_conflict")

    if item.get("recommendation") == "include" and item.get("claim_type") not in INCLUDE_CLAIM_TYPES:
        item["recommendation"] = "review"
        item["confidence"] = _lower_confidence(item.get("confidence"))
        reasons.append("include_claim_type_not_strong")

    item["target_reference_marker"] = target_marker_text
    item["evidence_reference_marker"] = f"[{evidence_marker}]" if evidence_marker else target_marker_text
    item["evidence_reference_entry_raw"] = evidence_reference_entry_raw
    item["reference_match_status"] = reference_match_status
    item["reference_match_reason"] = reference_match_reason
    item["normalized_target_reference"] = target_reference_entry
    item["citation_text_contains_target_marker"] = quote_has_target_marker
    item["citation_text_contains_other_marker"] = quote_has_other_marker
    item["target_reference_entry_matches_target"] = entry_matches_target
    item["reference_attribution_conflict"] = attribution_conflict
    item["reference_attribution_body_author"] = body_author
    item["reference_attribution_entry_author"] = reference_author
    item["reference_attribution_reason"] = (
        "body_author_reference_author_mismatch" if attribution_conflict else ""
    )
    if grouped_citation:
        item["grouped_citation"] = True
    else:
        item["grouped_citation"] = False
    if reasons:
        item["postprocess_reason"] = "; ".join(reasons)
        _append_reason(item, reasons[-1])
    return item


def _include_downgrade_reason(
    *,
    claim_type: str,
    quote: str,
    combined: str,
    has_target_marker: bool,
    grouped_citation: bool,
    title_alias_in_quote: bool,
    reference_match_status: str,
    reason_text: str,
) -> str:
    if reference_match_status != "matched":
        return "reference_match_not_matched"
    if _is_title_only_or_reference_only(quote, combined):
        return "title_or_reference_only_not_include"
    if claim_type not in INCLUDE_CLAIM_TYPES:
        if claim_type == "ordinary_reference":
            return "ordinary_reference_not_include"
        return "include_claim_type_not_strong"
    if not has_target_marker:
        return "include_requires_body_target_marker"
    if grouped_citation and not title_alias_in_quote:
        return "grouped_citation_requires_review"
    reverse_reason = _reverse_reason_downgrade(reason_text)
    if reverse_reason:
        return reverse_reason
    text = _normalize(combined)
    quote_text = _normalize(quote)
    if claim_type == "submm_precision_claim":
        if not _has_submm_term(quote_text):
            return "submm_claim_missing_body_submm_term"
        if not (
            _has_capability_terms(quote_text)
            or _has_method_use_terms(quote_text)
            or _has_performance_comparison_terms(quote_text)
        ):
            return "submm_claim_missing_body_capability_term"
    if claim_type == "through_wall_eavesdropping" and not _has_through_wall_term(text):
        return "through_wall_claim_missing_body_term"
    if claim_type == "rfid_loudspeaker_vibration" and not _has_loudspeaker_vibration_terms(text):
        return "rfid_loudspeaker_claim_missing_body_terms"
    if claim_type == "performance_comparison" and not _has_performance_comparison_terms(text):
        return "performance_comparison_missing_concrete_terms"
    if claim_type == "method_use" and not _has_method_use_terms(text):
        return "method_use_missing_concrete_terms"
    if claim_type == "capability_recognition" and not _has_capability_terms(text):
        return "capability_recognition_missing_concrete_terms"
    if claim_type in {"capability_recognition", "method_use"} and not (
        _has_submm_term(quote_text)
        or _has_through_wall_term(text)
        or _has_loudspeaker_vibration_terms(text)
        or _has_performance_comparison_terms(text)
        or _has_specific_method_use_scope(text)
    ):
        return "generic_rfid_eavesdropping_not_include"
    return ""


def _infer_stronger_claim_type(
    *,
    claim_type: str,
    quote: str,
    combined: str,
    reason_text: str,
    has_target_marker: bool,
    reference_match_status: str,
    grouped_citation: bool,
    limitation_reason: str,
) -> str:
    """Promote obvious direct evidence categories after reference validation."""
    if reference_match_status == "mismatch" or not has_target_marker:
        return claim_type
    if limitation_reason:
        return "limitation_feedback"
    if _submm_scope_negative_reason(reason_text):
        return claim_type
    if _is_title_only_or_reference_only(quote, combined):
        return claim_type
    quote_text = _normalize(quote)
    combined_text = _normalize(combined)
    if _has_submm_term(quote_text) and (
        _has_capability_terms(quote_text)
        or _has_method_use_terms(quote_text)
        or _has_performance_comparison_terms(quote_text)
    ):
        return _stronger_claim_type(claim_type, "submm_precision_claim")
    if _has_through_wall_term(quote_text) and _has_capability_terms(quote_text):
        return _stronger_claim_type(claim_type, "through_wall_eavesdropping")
    if (
        _has_through_wall_term(combined_text)
        and _has_capability_terms(combined_text)
        and not grouped_citation
    ):
        return _stronger_claim_type(claim_type, "through_wall_eavesdropping")
    if _has_loudspeaker_vibration_terms(combined_text):
        return _stronger_claim_type(claim_type, "rfid_loudspeaker_vibration")
    return claim_type


def _stronger_claim_type(current: str, candidate: str) -> str:
    return candidate if CLAIM_PRIORITY.get(candidate, 0) > CLAIM_PRIORITY.get(current, 0) else current


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
        "grouped_citation_requires_review": "成组引用没有单独描述目标论文，需进入候选复核。",
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
    }.get(reason, reason)
    existing = str(item.get("why_this_judgment_zh") or "").strip()
    if reason_zh and reason_zh not in existing:
        item["why_this_judgment_zh"] = (existing + " " + reason_zh).strip()


def _reference_entry_matches_target(
    reference_entry: str,
    *,
    cited_paper_title: str,
    cited_paper_doi: Optional[str],
) -> bool:
    entry = _normalize(reference_entry)
    if not entry:
        return False
    doi = _normalize_doi(cited_paper_doi)
    if doi and doi in _normalize_doi(reference_entry):
        return True
    title = _normalize(cited_paper_title)
    if title and title in entry:
        return True
    title_tokens = _meaningful_tokens(title)
    entry_tokens = set(_meaningful_tokens(entry))
    if len(title_tokens) < 3:
        return bool(title_tokens and set(title_tokens).issubset(entry_tokens))
    overlap = len(set(title_tokens) & entry_tokens) / max(1, len(set(title_tokens)))
    return overlap >= 0.65


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


def _infer_summary_claim_type(target_scope: str) -> str:
    """Give substantive target-specific summaries a reviewable semantic label."""
    normalized = _normalize(target_scope)
    if len(_meaningful_tokens(normalized)) < 5:
        return ""
    if re.search(
        r"\b(achieve[sd]?|demonstrate[sd]?|enable[sd]?|detect\w*|measure[sd]?|"
        r"capture[sd]?|recogniz\w*|support[sd]?)\b",
        normalized,
        flags=re.I,
    ):
        return "capability_summary"
    if re.search(
        r"\b(propose[sd]?|introduce[sd]?|present[sd]?|develop\w*|use[sd]?|using|"
        r"employ\w*|leverag\w*|extend\w*|implement\w*|based\s+on)\b",
        normalized,
        flags=re.I,
    ):
        return "method_summary"
    return ""


def _clean_marker(marker: str) -> str:
    value = str(marker or "").strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1].strip()
    return value


def _has_submm_term(text: str) -> bool:
    return bool(
        re.search(
            r"\b(sub\s*-?\s*mm|sub\s*-?\s*millimeter|sub\s*-?\s*millimetre|millimeter\s*-?\s*level|millimetre\s*-?\s*level|mm\s*-?\s*level)\b",
            text,
            flags=re.I,
        )
    )


def _has_through_wall_term(text: str) -> bool:
    return bool(re.search(r"\b(thr(?:ough|u)\s*-?\s*the\s*-?\s*wall|thr(?:ough|u)\s*-?\s*wall)\b", text, flags=re.I))


def _has_loudspeaker_vibration_terms(text: str) -> bool:
    has_rfid = "rfid" in text
    has_speaker = bool(re.search(r"\b(loudspeaker|speaker|acoustic|voice|audio)\b", text, flags=re.I))
    has_vibration = bool(re.search(r"\b(vibration|vibrations|vibrat\w+)\b", text, flags=re.I))
    return has_rfid and has_speaker and has_vibration


def _has_method_use_terms(text: str) -> bool:
    return bool(
        re.search(
            r"\b(use[sd]?|using|adopt\w*|follow\w*|according\s+to|implement\w*|based\s+on|build\w*\s+on|extend\w*)\b",
            text,
            flags=re.I,
        )
    )


def _has_specific_method_use_scope(text: str) -> bool:
    return bool(
        re.search(
            r"\b(reconstruct\w*\s+audio|captur\w+\s+vibrations?\s+from\s+loudspeakers?|vibration\s+pattern|speaker\s+vibration|loudspeaker\s+vibration|cgan|baseline|implementation)\b",
            text,
            flags=re.I,
        )
    )


def _has_performance_comparison_terms(text: str) -> bool:
    return bool(
        re.search(
            r"\b(compare[sd]?|comparison|baseline|benchmark|performance|accuracy|error|outperform\w*|superior|inferior|improve\w*)\b",
            text,
            flags=re.I,
        )
    )


def _has_capability_terms(text: str) -> bool:
    return bool(
        re.search(
            r"\b(achieve[sd]?|demonstrate[sd]?|enable[sd]?|recogniz\w*|capabilit\w*|support[sd]?|measure[sd]?|detect\w*|captur\w*)\b",
            text,
            flags=re.I,
        )
    )


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


def _reverse_reason_downgrade(reason_text: str) -> str:
    normalized = _normalize(reason_text)
    raw_text = str(reason_text or "").casefold()
    weak_phrases = (
        "ordinary related work",
        "ordinary reference",
        "general reference",
        "general listing",
        "listed",
        "not specifically mention",
        "not specifically discussed",
        "not explicitly mention sub mm",
        "title itself",
        "title only",
        "reference only",
        "attribution risk",
        "grouped citation",
        "limitation",
        "limited",
        "less practical",
        "background",
        "普通相关工作",
        "普通引用",
        "一般性引用",
        "一般性列举",
        "列举",
        "未具体提及",
        "未给出",
        "未展开讨论",
        "未明确提及 sub mm",
        "没有明确",
        "没有具体",
        "no specific",
        "does not provide",
    )
    weak_raw_phrases = (
        "普通相关工作",
        "普通引用",
        "一般性引用",
        "一般性列举",
        "列举",
        "未具体提及",
        "未给出",
        "未展开讨论",
        "未明确提及 sub-mm",
        "未明确提及 submm",
        "没有明确",
        "没有具体",
        "标题本身",
        "成组引用",
        "分组引用",
        "局限性",
        "受限",
        "不适合",
        "仅作为例子",
        "仅作为背景",
    )
    return (
        "reason_text_indicates_weak_evidence"
        if any(phrase in normalized for phrase in weak_phrases)
        or any(phrase.casefold() in raw_text for phrase in weak_raw_phrases)
        else ""
    )


def _submm_scope_negative_reason(reason_text: str) -> bool:
    normalized = _normalize(reason_text)
    phrases = (
        "sub mm does not apply to target",
        "sub mm is not attributed to target",
        "sub mm modifies another system",
        "sub mm 修饰 another system",
        "sub mm 不修饰",
        "未作用到目标论文",
        "不作用到目标论文",
        "未归因到目标论文",
    )
    return any(phrase in normalized for phrase in phrases)


def _limitation_downgrade_reason(text: str) -> str:
    normalized = _normalize(text)
    limitation_phrases = (
        "less practical",
        "requires pre-installing",
        "requires pre installing",
        "requires pre-installed",
        "requires pre installed",
        "pre-installed tag",
        "pre installed tag",
        "pre-installing rfid tags",
        "pre installing rfid tags",
        "limited",
        "not a good candidate",
        "insufficient vibration resolution",
        "accuracy is limited",
        "long wavelength",
        "lower packet rate",
        "reduces practicality",
        "requires stable wireless conditions",
        "not practical",
        "impractical",
    )
    return "limitation_language_not_include" if any(phrase in normalized for phrase in limitation_phrases) else ""


def _lower_confidence(value: Any) -> str:
    return "low" if str(value or "").lower() == "low" else "medium"


def _join_reason(existing: Any, reason: str) -> str:
    parts = [part.strip() for part in str(existing or "").split(";") if part.strip()]
    if reason not in parts:
        parts.append(reason)
    return "; ".join(parts)


def _normalize_quote(text: str) -> str:
    return re.sub(r"\s+", " ", _normalize(text)).strip()


def _normalize_doi(text: Optional[str]) -> str:
    value = str(text or "").strip().lower()
    match = re.search(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", value)
    return match.group(0).rstrip(".,;") if match else value


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

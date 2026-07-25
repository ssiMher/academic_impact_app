"""Deterministic template matching helpers."""

import json
import re
from typing import Iterable, List, Optional, Tuple

from app.models import AnalysisTemplate


TEMPLATE_CONTRACTS = {
    "first_or_pioneering_claim": {
        "allowed_evidence_types": [
            "first_or_pioneering_claim",
            "first_or_seminal_claim",
        ],
        "strict_rules": [
            "requires an explicit first, pioneering, earliest, or seminal expression in body text",
            "the expression must modify the target paper anchor",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
    "first_or_seminal_claim": {
        "allowed_evidence_types": ["first_or_seminal_claim"],
        "strict_rules": [
            "requires an explicit first, pioneering, earliest, or seminal expression in body text",
            "the expression must modify the target paper anchor",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
    "detailed_comparison": {
        "allowed_evidence_types": [
            "detailed_comparison",
            "performance_comparison",
        ],
        "strict_rules": [
            "requires a substantive multi-sentence or metric-backed comparison",
            "a passing compared-with phrase is insufficient",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
    "baseline_or_benchmark": {
        "allowed_evidence_types": [
            "baseline_or_benchmark",
            "performance_comparison",
        ],
        "strict_rules": [
            "requires explicit use as a baseline or benchmark",
            "requires experimental, table, reproduction, or performance-comparison context",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
    "positive_evaluation": {
        "allowed_evidence_types": [
            "positive_evaluation",
            "capability_recognition",
            "capability_summary",
            "method_summary",
            "rfid_loudspeaker_vibration",
            "through_wall_eavesdropping",
        ],
        "strict_rules": [
            "requires explicit positive evaluation of the target paper's capability, contribution, effect, or value",
            "a capability description alone is insufficient without evaluative language",
            "limitation feedback and ordinary related work are not positive evaluation",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
}


def load_json_list(value: str) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def match_template_terms(template: AnalysisTemplate, text: str) -> Tuple[List[str], str, float]:
    lowered = (text or "").lower()
    scoring_rules = _load_json_object(template.scoring_rules_json)
    if template.template_type == "long_context_citation":
        chars = len(text or "")
        words = len((text or "").split())
        min_chars = int(scoring_rules.get("min_citation_chars", 0) or 0)
        min_words = int(scoring_rules.get("min_citation_words", 0) or 0)
        require_target_marker = bool(scoring_rules.get("require_target_marker", False))
        if min_chars and chars < min_chars:
            return [], "", 0.0
        if min_words and words < min_words:
            return [], "", 0.0
        if require_target_marker and "[" not in (text or ""):
            return [], "", 0.0
        matched = []
        if min_chars:
            matched.append(f"min_citation_chars>={min_chars}")
        if min_words:
            matched.append(f"min_citation_words>={min_words}")
        if require_target_marker:
            matched.append("require_target_marker")
        score = min(30.0, 10.0 + len(matched) * 5.0)
        reason = f"Matched long_context_citation rules: {', '.join(matched)}"
        return matched, reason, score
    candidates = []
    candidates.extend(load_json_list(template.positive_keywords_json))
    candidates.extend(load_json_list(template.required_evidence_patterns_json))
    candidates.extend(load_json_list(template.target_aspects_json))

    matched = []
    seen = set()
    for term in candidates:
        normalized = " ".join(term.strip().split())
        if not normalized:
            continue
        lowered_term = normalized.lower()
        if lowered_term in lowered and lowered_term not in seen:
            seen.add(lowered_term)
            matched.append(normalized)

    if not matched:
        return [], "", 0.0

    score = min(30.0, 10.0 * len(matched))
    reason = f"Matched template '{template.name}' terms: {', '.join(matched)}"
    return matched, reason, score


def template_snapshot(template: AnalysisTemplate) -> dict:
    """Return a prompt/report safe template snapshot."""
    rules = _load_json_object(template.scoring_rules_json)
    contract = TEMPLATE_CONTRACTS.get(template.template_type, {})
    return {
        "template_id": template.id,
        "name": template.name,
        "display_name": template.description or template.name,
        "template_type": template.template_type,
        "goal": template.natural_language_goal,
        "positive_keywords": load_json_list(template.positive_keywords_json),
        "negative_keywords": load_json_list(template.negative_keywords_json),
        "required_patterns": load_json_list(template.required_evidence_patterns_json),
        "allowed_evidence_types": rules.get("allowed_evidence_types")
        or contract.get("allowed_evidence_types")
        or load_json_list(template.target_aspects_json),
        "strict_rules": rules.get("strict_rules")
        or contract.get("strict_rules")
        or [],
        "min_citation_text_chars": int(rules.get("min_citation_chars", 0) or 0),
        "min_citation_text_words": int(rules.get("min_citation_words", 0) or 0),
        "require_target_marker": bool(
            rules.get(
                "require_target_marker",
                contract.get("require_target_marker", False),
            )
        ),
        "allow_grouped_citation": bool(
            rules.get(
                "allow_grouped_citation",
                contract.get("allow_grouped_citation", False),
            )
        ),
        "auto_include": bool(rules.get("auto_include_in_report", False)),
        "instruction_text": template.prompt_fragment or "",
        "scoring_rules": rules,
        "prompt_fragment": template.prompt_fragment or "",
    }


def format_template_snapshots_for_prompt(templates: List[AnalysisTemplate]) -> str:
    if not templates:
        return "(none)"
    return json.dumps(
        [template_snapshot(template) for template in templates],
        ensure_ascii=False,
        indent=2,
    )


def evaluate_templates_for_finding(
    templates: List[AnalysisTemplate],
    finding_payload: dict,
    *,
    citation_text: str,
    evidence_context: str = "",
    target_reference_marker: str = "",
    cited_paper_title: str = "",
) -> dict:
    """Evaluate active templates after LLM output.

    This is intentionally conservative: satisfied templates require body quote
    evidence and template-specific textual support. It also records why active
    templates did not match so reports can explain template behavior.
    """
    evaluations = []
    matched_ids: List[int] = []
    matched_names: List[str] = []
    match_reasons: List[str] = []
    failure_reasons: List[str] = []
    text = " ".join(
        [
            citation_text or "",
            evidence_context or "",
            str(finding_payload.get("reasoning") or ""),
            " ".join(finding_payload.get("keywords") or []),
        ]
    )
    for template in templates:
        evaluation = _evaluate_single_template(
            template,
            finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            combined_text=text,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
        evaluations.append(evaluation)
        if evaluation["template_satisfied"]:
            matched_ids.append(template.id)
            matched_names.append(template.description or template.name)
            match_reasons.append(evaluation["template_match_reason"])
        else:
            failure_reasons.append(
                f"{template.description or template.name}: {evaluation['template_failure_reason']}"
            )
    return {
        "matched_template_ids": matched_ids,
        "matched_template_names": matched_names,
        "template_match_reason": "; ".join(reason for reason in match_reasons if reason),
        "template_satisfied": bool(matched_ids),
        "template_failure_reason": "; ".join(reason for reason in failure_reasons if reason),
        "template_evaluations": evaluations,
    }


def _evaluate_single_template(
    template: AnalysisTemplate,
    finding_payload: dict,
    *,
    citation_text: str,
    evidence_context: str,
    combined_text: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> dict:
    is_template_direct_finding = bool(finding_payload.get("claim_type"))
    if template.template_type in {
        "first_or_seminal_claim",
        "first_or_pioneering_claim",
    }:
        return _evaluate_first_pioneering_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            combined_text=combined_text,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    if is_template_direct_finding and template.template_type == "detailed_comparison":
        return _evaluate_detailed_comparison_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    if is_template_direct_finding and template.template_type == "baseline_or_benchmark":
        return _evaluate_baseline_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    if is_template_direct_finding and template.template_type == "positive_evaluation":
        return _evaluate_positive_evaluation_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    return _evaluate_configured_template(
        template,
        finding_payload,
        citation_text=citation_text,
        evidence_context=evidence_context,
        combined_text=combined_text,
        target_reference_marker=target_reference_marker,
        cited_paper_title=cited_paper_title,
    )


def _evaluate_configured_template(
    template: AnalysisTemplate,
    finding_payload: dict,
    *,
    citation_text: str,
    evidence_context: str,
    combined_text: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> dict:
    rules = _effective_rules(template)
    user_defined = (
        rules.get("template_origin") == "user_defined"
        or template.name.startswith("custom_")
    )
    positive_terms = load_json_list(template.positive_keywords_json)
    negative_terms = load_json_list(template.negative_keywords_json)
    required_patterns = load_json_list(template.required_evidence_patterns_json)
    quote = citation_text or ""
    context = evidence_context or quote
    normalized_text = _normalize_for_match(f"{quote} {context}")
    matched_positive = [term for term in positive_terms if _term_in_text(term, normalized_text)]
    matched_required = [term for term in required_patterns if _term_in_text(term, normalized_text)]
    matched_negative = [term for term in negative_terms if _term_in_text(term, normalized_text)]
    finding_keywords = [
        str(term).strip()
        for term in finding_payload.get("keywords", []) or []
        if str(term).strip()
    ]
    matched_finding_keywords = [
        keyword
        for keyword in finding_keywords
        if any(
            configured in _normalize_for_match(keyword)
            or _normalize_for_match(keyword) in configured
            for configured in (
                _normalize_for_match(term)
                for term in [*positive_terms, *required_patterns]
                if _normalize_for_match(term)
            )
        )
    ]
    marker_required = bool(rules.get("require_target_marker", False)) or user_defined
    has_anchor = _has_target_anchor(quote, target_reference_marker, cited_paper_title)
    grouped = _is_grouped_citation(quote, target_reference_marker)
    min_chars = int(rules.get("min_citation_chars", 0) or 0)
    min_words = int(rules.get("min_citation_words", 0) or 0)
    allowed_types = rules.get("allowed_evidence_types") or (
        [] if user_defined else load_json_list(template.target_aspects_json)
    )
    evidence_type = str(
        finding_payload.get("evidence_type")
        or finding_payload.get("claim_type")
        or ""
    )
    model_ids = {
        int(value)
        for value in finding_payload.get("matched_template_ids", []) or []
        if str(value).isdigit()
    }
    model_support = template.id in model_ids and finding_payload.get("template_satisfied") is not False
    builtin_type_support = bool(
        not user_defined
        and evidence_type
        and allowed_types
        and evidence_type in allowed_types
    )

    failure = ""
    if not quote.strip():
        failure = "no citation_text body evidence"
    elif str(finding_payload.get("reference_match_status") or "") == "mismatch":
        failure = "reference mismatch"
    elif _looks_like_title_or_reference_only(quote, cited_paper_title):
        failure = "title-only or reference-only evidence does not satisfy the template"
    elif marker_required and not has_anchor:
        failure = "citation_text does not anchor to target paper"
    elif grouped and not bool(rules.get("allow_grouped_citation", False)):
        failure = "grouped citation is not allowed by this template"
    elif min_chars and len(quote) < min_chars:
        failure = f"citation_text shorter than min_citation_chars={min_chars}"
    elif min_words and len(quote.split()) < min_words:
        failure = f"citation_text shorter than min_citation_words={min_words}"
    elif matched_negative:
        failure = "matched exclusion terms: " + ", ".join(matched_negative)
    elif user_defined and required_patterns and not matched_required:
        failure = "no required evidence pattern matched"
    elif allowed_types and evidence_type and evidence_type not in allowed_types:
        failure = f"evidence type {evidence_type} is not allowed by the template"
    elif _is_weak_related_work(finding_payload, quote) and not _has_substantive_action(quote):
        failure = "plain related work without a substantive target-specific claim"
    elif not (
        model_support
        or builtin_type_support
        or matched_required
        or _has_specific_positive_support(matched_positive)
    ):
        failure = "no substantive configured concept matched in body evidence"

    matched_terms = list(
        dict.fromkeys([*matched_required, *matched_positive, *matched_finding_keywords])
    )
    satisfied = not failure
    reason = (
        "body evidence satisfies the configured template"
        + (": " + ", ".join(matched_terms[:8]) if matched_terms else "")
        if satisfied
        else ""
    )
    return {
        "template_id": template.id,
        "template_name": template.description or template.name,
        "template_type": template.template_type,
        "template_satisfied": satisfied,
        "template_match_reason": reason,
        "template_failure_reason": failure,
        "matched_terms": matched_terms,
        "match_score": min(30.0, 15.0 + len(matched_terms) * 5.0) if satisfied else 0.0,
        "auto_include_in_report": bool(rules.get("auto_include_in_report", False)),
    }


def _evaluate_first_pioneering_template(
    template: AnalysisTemplate,
    *,
    finding_payload: dict,
    citation_text: str,
    combined_text: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> dict:
    body = citation_text or ""
    guard_failure = _strict_template_guard(
        template,
        finding_payload=finding_payload,
        citation_text=body,
        target_reference_marker=target_reference_marker,
        cited_paper_title=cited_paper_title,
    )
    matched = _matched_terms(
        _normalize(body),
        [
            "the first",
            "first ",
            "first-of-its-kind",
            "for the first time",
            "pioneering",
            "seminal",
            "earliest",
            "首次",
            "开创性",
            "率先",
            "最早",
        ],
    )
    scope_ok, scope_reason = _first_expression_targets_cited_paper(
        body,
        matched_terms=matched,
        target_reference_marker=target_reference_marker,
        cited_paper_title=cited_paper_title,
    )
    satisfied = not guard_failure and bool(matched) and scope_ok
    if guard_failure:
        failure = guard_failure
    elif not matched:
        failure = "no explicit first/pioneering expression in body text"
    elif not scope_ok:
        failure = scope_reason
    else:
        failure = ""
    return {
        "template_id": template.id,
        "template_name": template.description or template.name,
        "template_type": template.template_type,
        "template_satisfied": satisfied,
        "template_match_reason": (
            "explicit first/pioneering expression targets cited paper: " + ", ".join(matched)
            if satisfied
            else ""
        ),
        "template_failure_reason": failure,
        "matched_terms": matched,
        "match_score": 30.0 if satisfied else 0.0,
    }


def _evaluate_detailed_comparison_template(
    template: AnalysisTemplate,
    *,
    finding_payload: dict,
    citation_text: str,
    evidence_context: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> dict:
    guard_failure = _strict_template_guard(
        template,
        finding_payload=finding_payload,
        citation_text=citation_text,
        target_reference_marker=target_reference_marker,
        cited_paper_title=cited_paper_title,
    )
    text = f"{citation_text} {evidence_context}"
    has_comparison = bool(re.search(r"\b(compar\w*|versus|vs\.?|relative\s+to)\b", text, re.I))
    has_detail = bool(
        re.search(
            r"\b(table|experiment\w*|performance|accuracy|error|latency|throughput|"
            r"metric|result\w*|outperform\w*|higher|lower|faster|slower|whereas|however)\b|%",
            text,
            re.I,
        )
    )
    sentence_count = len(
        [part for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", text) if part.strip()]
    )
    claim_type = str(finding_payload.get("claim_type") or "")
    type_ok = claim_type in {"detailed_comparison", "performance_comparison"}
    satisfied = (
        not guard_failure
        and type_ok
        and has_comparison
        and has_detail
        and (sentence_count >= 2 or len(evidence_context or "") >= 220)
    )
    if guard_failure:
        failure = guard_failure
    elif not type_ok:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif not has_comparison:
        failure = "no explicit comparison expression in body text"
    elif not has_detail or (sentence_count < 2 and len(evidence_context or "") < 220):
        failure = "comparison is too brief or lacks concrete method/performance detail"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=satisfied,
        reason="target-anchored substantive comparison with concrete details",
        failure=failure,
        matched_terms=["comparison", "concrete comparison detail"] if satisfied else [],
    )


def _evaluate_baseline_template(
    template: AnalysisTemplate,
    *,
    finding_payload: dict,
    citation_text: str,
    evidence_context: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> dict:
    guard_failure = _strict_template_guard(
        template,
        finding_payload=finding_payload,
        citation_text=citation_text,
        target_reference_marker=target_reference_marker,
        cited_paper_title=cited_paper_title,
    )
    text = f"{citation_text} {evidence_context}"
    has_baseline = bool(re.search(r"\b(baseline|benchmark)\b", text, re.I))
    has_evaluation = bool(
        re.search(
            r"\b(table|experiment\w*|evaluat\w*|compar\w*|reproduc\w*|implement\w*|"
            r"performance|accuracy|error|metric|result\w*)\b",
            text,
            re.I,
        )
    )
    claim_type = str(finding_payload.get("claim_type") or "")
    type_ok = claim_type in {"baseline_or_benchmark", "performance_comparison"}
    satisfied = not guard_failure and type_ok and has_baseline and has_evaluation
    if guard_failure:
        failure = guard_failure
    elif not type_ok:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif not has_baseline:
        failure = "target paper is not explicitly used as a baseline or benchmark"
    elif not has_evaluation:
        failure = "baseline mention lacks experimental or performance-comparison context"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=satisfied,
        reason="target paper is explicitly used as an evaluated baseline or benchmark",
        failure=failure,
        matched_terms=["baseline or benchmark", "evaluation context"] if satisfied else [],
    )


def _evaluate_positive_evaluation_template(
    template: AnalysisTemplate,
    *,
    finding_payload: dict,
    citation_text: str,
    evidence_context: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> dict:
    guard_failure = _strict_template_guard(
        template,
        finding_payload=finding_payload,
        citation_text=citation_text,
        target_reference_marker=target_reference_marker,
        cited_paper_title=cited_paper_title,
    )
    text = f"{citation_text} {evidence_context}"
    claim_type = str(finding_payload.get("claim_type") or "")
    allowed_types = set(
        TEMPLATE_CONTRACTS["positive_evaluation"]["allowed_evidence_types"]
    )
    has_positive_language = bool(
        re.search(
            r"\b(effective|accurate|robust|valuable|significant|important|promising|"
            r"novel|strong|superior|outperform\w*|improv\w*|high[- ]precision|"
            r"high[- ]accuracy|state[- ]of[- ]the[- ]art)\b|"
            r"(有效|准确|鲁棒|重要|显著|优越|领先|高精度|有价值)",
            text,
            re.I,
        )
    )
    has_limitation = bool(
        re.search(
            r"\b(limitation|limited|less practical|impractical|drawback|weakness|"
            r"insufficient|not practical|requires pre-installing)\b|"
            r"(局限|不足|受限|不实用)",
            text,
            re.I,
        )
    )
    type_ok = claim_type in allowed_types
    satisfied = (
        not guard_failure
        and type_ok
        and has_positive_language
        and not has_limitation
    )
    if guard_failure:
        failure = guard_failure
    elif not type_ok:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif has_limitation:
        failure = "limitation feedback cannot satisfy positive evaluation"
    elif not has_positive_language:
        failure = "no explicit positive evaluation of capability, contribution, effect, or value"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=satisfied,
        reason="explicit target-anchored positive evaluation in body text",
        failure=failure,
        matched_terms=["explicit positive evaluation"] if satisfied else [],
    )


def _effective_rules(template: AnalysisTemplate) -> dict:
    rules = _load_json_object(template.scoring_rules_json)
    contract = TEMPLATE_CONTRACTS.get(template.template_type, {})
    effective = dict(contract)
    effective.update(rules)
    if (
        not effective.get("allowed_evidence_types")
        and effective.get("template_origin") != "user_defined"
    ):
        effective["allowed_evidence_types"] = load_json_list(
            template.target_aspects_json
        )
    return effective


def _strict_template_guard(
    template: AnalysisTemplate,
    *,
    finding_payload: dict,
    citation_text: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> str:
    rules = _effective_rules(template)
    if not citation_text.strip():
        return "no citation_text body evidence"
    if str(finding_payload.get("reference_match_status") or "") == "mismatch":
        return "reference mismatch"
    if _looks_like_title_or_reference_only(citation_text, cited_paper_title):
        return "title-only or reference-only evidence does not satisfy the template"
    if bool(rules.get("require_target_marker", False)) and not _has_target_anchor(
        citation_text,
        target_reference_marker,
        cited_paper_title,
    ):
        return "citation_text does not anchor to target paper"
    if _is_grouped_citation(citation_text, target_reference_marker) and not bool(
        rules.get("allow_grouped_citation", False)
    ):
        return "grouped citation is not allowed by this template"
    return ""


def _template_evaluation(
    template: AnalysisTemplate,
    *,
    satisfied: bool,
    reason: str,
    failure: str,
    matched_terms: List[str],
) -> dict:
    return {
        "template_id": template.id,
        "template_name": template.description or template.name,
        "template_type": template.template_type,
        "template_satisfied": satisfied,
        "template_match_reason": reason if satisfied else "",
        "template_failure_reason": failure,
        "matched_terms": matched_terms,
        "match_score": 30.0 if satisfied else 0.0,
        "auto_include_in_report": False,
    }


def _first_expression_targets_cited_paper(
    citation_text: str,
    *,
    matched_terms: List[str],
    target_reference_marker: str,
    cited_paper_title: str,
) -> Tuple[bool, str]:
    if not matched_terms:
        return False, "no explicit first/pioneering expression in body text"
    text = citation_text or ""
    lowered = text.lower()
    first_positions = []
    for term in matched_terms:
        term_lower = term.strip().lower()
        if not term_lower:
            continue
        pos = lowered.find(term_lower)
        if pos >= 0:
            first_positions.append(pos)
    if not first_positions:
        return False, "no explicit first/pioneering expression in body text"

    anchors = []
    marker = (target_reference_marker or "").strip()
    if marker and marker in text:
        anchors.append(text.find(marker))
    for alias in _title_aliases(cited_paper_title):
        pos = lowered.find(alias.lower())
        if pos >= 0:
            anchors.append(pos)
    if not anchors:
        return False, "first/pioneering expression has no target title or reference marker anchor"

    # The scope check is intentionally local: a first/pioneering expression must
    # be close enough to the target anchor to modify the target paper, not an
    # unrelated method earlier in the sentence.
    for first_pos in first_positions:
        for anchor_pos in anchors:
            if abs(first_pos - anchor_pos) <= 80:
                between = lowered[min(first_pos, anchor_pos):max(first_pos, anchor_pos)]
                if any(token in between for token in ["unlike", "whereas", "while ", "rather than", "compared with"]):
                    continue
                return True, ""
    return False, "explicit first/pioneering expression does not modify the target paper"


def _normalize_for_match(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (value or "").lower()).split())


def _term_in_text(term: str, normalized_text: str) -> bool:
    normalized_term = _normalize_for_match(term)
    return bool(normalized_term and normalized_term in normalized_text)


def _has_specific_positive_support(matched_terms: List[str]) -> bool:
    for term in matched_terms:
        normalized = _normalize_for_match(term)
        tokens = normalized.split()
        if len(tokens) >= 2 or len(normalized) >= 8:
            return True
    return False


def _is_grouped_citation(citation_text: str, target_marker: str) -> bool:
    markers = set(re.findall(r"\d+", " ".join(re.findall(r"\[[^\]]+\]", citation_text or ""))))
    marker = "".join(re.findall(r"\d+", target_marker or ""))
    return bool(marker and marker in markers and len(markers) > 1)


def _looks_like_title_or_reference_only(citation_text: str, cited_paper_title: str) -> bool:
    normalized_quote = _normalize_for_match(re.sub(r"\[[^\]]+\]", "", citation_text or ""))
    normalized_title = _normalize_for_match(cited_paper_title)
    if not normalized_quote:
        return True
    if normalized_title and (
        normalized_quote == normalized_title
        or (normalized_title in normalized_quote and len(normalized_quote.split()) <= len(normalized_title.split()) + 3)
    ):
        return True
    return bool(
        re.search(r"\b(references?|bibliography|title[- ]only|reference[- ]only)\b", citation_text or "", flags=re.I)
    )


def _is_weak_related_work(finding_payload: dict, citation_text: str) -> bool:
    text = " ".join(
        [
            citation_text or "",
            str(finding_payload.get("reasoning") or ""),
            str(finding_payload.get("mention_type") or ""),
            str(finding_payload.get("claim_type") or ""),
        ]
    ).lower()
    return any(
        phrase in text
        for phrase in (
            "related work",
            "ordinary reference",
            "background reference",
            "listed",
            "列举",
            "普通引用",
            "普通相关工作",
        )
    )


def _has_substantive_action(citation_text: str) -> bool:
    return bool(
        re.search(
            r"\b(achiev\w*|demonstrat\w*|detect\w*|measur\w*|captur\w*|enable\w*|use[sd]?|using|adopt\w*|extend\w*|compar\w*|outperform\w*|improv\w*|reconstruct\w*)\b",
            citation_text or "",
            flags=re.I,
        )
    )


def _has_target_anchor(citation_text: str, marker: str, cited_title: str) -> bool:
    text = citation_text or ""
    if marker and marker in text:
        return True
    short_names = _title_aliases(cited_title)
    lowered = text.lower()
    return any(alias and alias.lower() in lowered for alias in short_names)


def _title_aliases(title: str) -> List[str]:
    title = title or ""
    aliases = []
    if ":" in title:
        aliases.append(title.split(":", 1)[0].strip())
    aliases.append(title)
    return [alias for alias in aliases if alias]


def _matched_terms(text: str, terms: List[str]) -> List[str]:
    matched = []
    for term in terms:
        if term.lower() in text and term not in matched:
            matched.append(term)
    return matched


def _normalize(value: str) -> str:
    return " ".join((value or "").lower().replace("–", "-").replace("—", "-").split())


def build_custom_prompt_fragment(
    *,
    natural_language_goal: str,
    template_type: str,
    positive_keywords: Iterable[str],
) -> str:
    keywords = ", ".join(keyword for keyword in positive_keywords if keyword)
    return (
        f"Template goal ({template_type}): {natural_language_goal}. "
        f"Prioritize evidence matching these terms: {keywords}. "
        "Still require original citation_text and avoid promoting grouped citation or weak mention."
    )


def _load_json_object(value: str) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

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
    "limitation_or_negative": {
        "allowed_evidence_types": [
            "limitation_feedback",
            "limitation_or_negative",
        ],
        "strict_rules": [
            "requires target-anchored body text that states a limitation, drawback, failure condition, or practical constraint",
            "ordinary related-work listing and neutral capability descriptions are insufficient",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
    "theoretical_foundation": {
        "allowed_evidence_types": [
            "theoretical_foundation",
            "method_foundation",
            "method_summary",
            "capability_summary",
        ],
        "strict_rules": [
            "requires target-anchored body text about a model, theory, equation, mechanism, or derivation",
            "plain listing and reference-only evidence are insufficient",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
    "method_foundation": {
        "allowed_evidence_types": [
            "method_foundation",
            "method_use",
            "method_summary",
        ],
        "strict_rules": [
            "requires target-anchored body text describing or using a concrete method from the target paper",
            "plain listing and reference-only evidence are insufficient",
            "a method summary without adoption or dependency is review-only",
        ],
        "require_target_marker": True,
        "allow_grouped_citation": False,
    },
    "method_or_capability_summary": {
        "allowed_evidence_types": [
            "method_summary",
            "capability_summary",
            "method_use",
            "capability_recognition",
        ],
        "strict_rules": [
            "requires a concrete body-text description of the target paper's method, mechanism, capability, or contribution",
            "plain listing, reference-only evidence, and unattributable grouped citation do not satisfy the template",
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
    snapshots = []
    for template in templates:
        snapshot = template_snapshot(template)
        snapshot["suggested_patterns"] = snapshot.pop("required_patterns", [])
        snapshot["suggested_evidence_types"] = snapshot.pop(
            "allowed_evidence_types",
            [],
        )
        snapshot["advisory_notes"] = snapshot.pop("strict_rules", [])
        snapshot["semantic_decision_policy"] = (
            "Use the template goal and the full citation context. All keywords, "
            "patterns, evidence types, and notes are advisory rather than hard gates."
        )
        snapshot["configured_allow_grouped_citation"] = snapshot.pop(
            "allow_grouped_citation",
            False,
        )
        snapshot["grouped_citation_policy"] = "model_semantic_attribution"
        snapshots.append(snapshot)
    return json.dumps(
        snapshots,
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
    strong_matched_ids: List[int] = []
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
        if (
            _is_grouped_citation(citation_text, target_reference_marker)
            and evaluation.get("template_match_level") == "strong"
            and not _model_accepts_grouped_attribution(finding_payload, template)
        ):
            evaluation = dict(evaluation)
            evaluation.update(
                {
                    "template_match_level": "candidate",
                    "template_strongly_satisfied": False,
                    "template_match_reason": (
                        f"{evaluation.get('template_match_reason') or 'template candidate'}; "
                        "grouped citation attribution awaits model judgment"
                    ),
                    "match_score": min(
                        float(evaluation.get("match_score") or 0.0),
                        20.0,
                    ),
                }
            )
        evaluations.append(evaluation)
        if evaluation["template_satisfied"]:
            matched_ids.append(template.id)
            matched_names.append(template.description or template.name)
            match_reasons.append(evaluation["template_match_reason"])
            if evaluation.get("template_match_level") == "strong":
                strong_matched_ids.append(template.id)
        else:
            failure_reasons.append(
                f"{template.description or template.name}: {evaluation['template_failure_reason']}"
            )
    match_level = (
        "strong"
        if strong_matched_ids
        else "candidate"
        if matched_ids
        else "none"
    )
    return {
        "matched_template_ids": matched_ids,
        "matched_template_names": matched_names,
        "strong_matched_template_ids": strong_matched_ids,
        "template_match_reason": "; ".join(reason for reason in match_reasons if reason),
        "template_satisfied": bool(matched_ids),
        "template_strongly_satisfied": bool(strong_matched_ids),
        "template_match_level": match_level,
        "template_failure_reason": "; ".join(reason for reason in failure_reasons if reason),
        "template_evaluations": evaluations,
    }


def _model_accepts_grouped_attribution(
    finding_payload: dict,
    template: AnalysisTemplate,
) -> bool:
    model_ids = {
        int(value)
        for value in finding_payload.get("matched_template_ids", []) or []
        if str(value).isdigit()
    }
    if template.id in model_ids and finding_payload.get("template_satisfied") is not False:
        return True
    recommendation = str(
        finding_payload.get("original_recommendation")
        or finding_payload.get("recommendation")
        or ""
    ).lower()
    claim_type = str(
        finding_payload.get("original_claim_type")
        or finding_payload.get("claim_type")
        or ""
    )
    compatible_claim_types = {
        "first_or_seminal_claim": {"first_or_seminal_claim", "first_or_pioneering_claim"},
        "first_or_pioneering_claim": {"first_or_seminal_claim", "first_or_pioneering_claim"},
        "detailed_comparison": {"detailed_comparison", "performance_comparison"},
        "baseline_or_benchmark": {"baseline_or_benchmark"},
        "theoretical_foundation": {"theoretical_foundation", "method_foundation"},
        "method_foundation": {
            "method_foundation",
            "method_use",
        },
        "positive_evaluation": {
            "positive_evaluation",
            "capability_recognition",
            "through_wall_eavesdropping",
            "rfid_loudspeaker_vibration",
        },
        "limitation_or_negative": {
            "limitation_feedback",
            "limitation_or_negative",
        },
        "method_or_capability_summary": {
            "method_summary",
            "capability_summary",
            "method_use",
            "capability_recognition",
        },
    }
    return (
        recommendation == "include"
        and claim_type in compatible_claim_types.get(template.template_type, set())
    )


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
    if (
        is_template_direct_finding
        and template.template_type == "limitation_or_negative"
    ):
        return _evaluate_limitation_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    if (
        is_template_direct_finding
        and template.template_type == "theoretical_foundation"
    ):
        return _evaluate_theoretical_foundation_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    if is_template_direct_finding and template.template_type == "method_foundation":
        return _evaluate_method_foundation_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    if (
        is_template_direct_finding
        and template.template_type == "method_or_capability_summary"
    ):
        return _evaluate_method_or_capability_summary_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )
    if (
        is_template_direct_finding
        and template_stance_intent(template) == "neutral"
    ):
        return _evaluate_neutral_attitude_template(
            template,
            finding_payload=finding_payload,
            citation_text=citation_text,
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


def template_stance_intent(template: AnalysisTemplate) -> str:
    text = " ".join(
        [
            str(template.template_type or ""),
            str(template.name or ""),
            str(template.description or ""),
            str(template.natural_language_goal or ""),
        ]
    ).casefold()
    # A neutral goal commonly says "neither positive nor negative", so detect
    # neutral intent before scanning those excluded sentiment words.
    if any(term in text for term in ("中性", "neutral")):
        return "neutral"
    if template.template_type == "limitation_or_negative" or any(
        term in text for term in ("负面", "局限", "negative evaluation")
    ):
        return "negative"
    if template.template_type == "positive_evaluation" or any(
        term in text for term in ("正向评价", "positive evaluation")
    ):
        return "positive"
    return ""


def _evaluate_neutral_attitude_template(
    template: AnalysisTemplate,
    *,
    finding_payload: dict,
    citation_text: str,
    target_reference_marker: str,
    cited_paper_title: str,
) -> dict:
    reference_status = str(finding_payload.get("reference_match_status") or "")
    claim_type = str(finding_payload.get("claim_type") or "")
    has_anchor = _has_target_anchor(
        citation_text,
        target_reference_marker,
        cited_paper_title,
    ) or bool(finding_payload.get("target_anchor_inherited", False))
    positive = bool(
        re.search(
            r"\b(effective\w*|robust|valuable|significant|important|promising|"
            r"novel|superior|outperform\w*|improv\w*|high[- ]precision|"
            r"high[- ]accuracy|success\w*)\b|"
            r"(有效|鲁棒|重要|显著|优越|领先|高精度|有价值)",
            citation_text,
            re.I,
        )
    )
    negative = bool(
        re.search(
            r"\b(limitation|limited|less practical|impractical|not practical|"
            r"drawback|weakness|insufficient|fails? to|cannot|can only|"
            r"constraint|shortcoming)\b|"
            r"(局限|不足|受限|不实用|只能|无法|缺点)",
            citation_text,
            re.I,
        )
    )
    substantive = (
        _has_method_or_capability_statement(citation_text)
        or _has_substantive_action(citation_text)
    )
    neutral_types = {
        "method_summary",
        "capability_summary",
        "method_use",
        "capability_recognition",
        "theoretical_foundation",
        "method_foundation",
        "ordinary_reference",
    }
    strong = (
        reference_status != "mismatch"
        and has_anchor
        and not positive
        and not negative
        and substantive
        and claim_type in neutral_types - {"ordinary_reference"}
    )
    candidate = (
        reference_status != "mismatch"
        and has_anchor
        and not positive
        and not negative
        and claim_type in neutral_types
        and not strong
    )
    if reference_status == "mismatch":
        failure = "reference mismatch"
    elif not has_anchor:
        failure = "citation_text does not anchor to target paper"
    elif _looks_like_title_or_reference_only(citation_text, cited_paper_title):
        failure = "title-only or reference-only evidence does not satisfy the template"
        strong = candidate = False
    elif positive:
        failure = "explicit positive evaluation is not neutral evidence"
    elif negative:
        failure = "limitation or negative evaluation is not neutral evidence"
    elif claim_type not in neutral_types:
        failure = f"evidence type {claim_type or 'unknown'} is not neutral evidence"
    elif not substantive:
        failure = "neutral mention lacks a substantive target-specific description"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=strong or candidate,
        reason=(
            "target-anchored factual method or capability description without positive or negative evaluation"
            if strong
            else "neutral target mention requires review because it lacks a substantive method or capability statement"
        ),
        failure=failure,
        matched_terms=(
            ["neutral target-specific description"]
            if strong
            else ["neutral mention candidate"]
            if candidate
            else []
        ),
        match_level="strong" if strong else "candidate",
    )


def _evaluate_method_or_capability_summary_template(
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
    if guard_failure:
        return _template_evaluation(
            template,
            satisfied=False,
            reason="",
            failure=guard_failure,
            matched_terms=[],
        )
    claim_type = str(finding_payload.get("claim_type") or "")
    allowed_types = set(
        _effective_rules(template).get("allowed_evidence_types") or []
    )
    if claim_type not in allowed_types:
        return _template_evaluation(
            template,
            satisfied=False,
            reason="",
            failure=f"evidence type {claim_type} is not allowed by the template",
            matched_terms=[],
        )
    combined = f"{citation_text} {evidence_context}".strip()
    if _is_weak_related_work(finding_payload, citation_text) and not _has_substantive_action(
        combined
    ):
        return _template_evaluation(
            template,
            satisfied=False,
            reason="",
            failure="plain related work without a substantive target-specific claim",
            matched_terms=[],
        )
    if not _has_method_or_capability_statement(combined):
        return _template_evaluation(
            template,
            satisfied=False,
            reason="",
            failure="no concrete method, mechanism, capability, or contribution statement",
            matched_terms=[],
        )
    return _template_evaluation(
        template,
        satisfied=True,
        reason="target-anchored body text concretely describes the paper's method, mechanism, or capability",
        failure="",
        matched_terms=[claim_type],
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
    candidate_support = bool(
        model_support
        or matched_required
        or builtin_type_support
        or len(matched_positive) >= 2
        or len(matched_finding_keywords) >= 2
    )
    hard_failure_prefixes = (
        "no citation_text",
        "reference mismatch",
        "title-only",
        "citation_text does not anchor",
        "citation_text shorter",
        "matched exclusion terms",
        "plain related work",
    )
    candidate = bool(
        failure
        and candidate_support
        and not failure.startswith(hard_failure_prefixes)
    )
    if not failure and grouped and not model_support:
        failure = "grouped citation attribution awaits model judgment"
        candidate = True
    satisfied = not failure or candidate
    match_level = "strong" if not failure else "candidate" if candidate else "none"
    reason = (
        (
            "body evidence satisfies the configured template"
            if match_level == "strong"
            else f"body evidence is a configured-template candidate; strict review pending: {failure}"
        )
        + (": " + ", ".join(matched_terms[:8]) if matched_terms else "")
        if satisfied
        else ""
    )
    return {
        "template_id": template.id,
        "template_name": template.description or template.name,
        "template_type": template.template_type,
        "template_satisfied": satisfied,
        "template_strongly_satisfied": match_level == "strong",
        "template_match_level": match_level,
        "template_match_reason": reason,
        "template_failure_reason": "" if satisfied else failure,
        "matched_terms": matched_terms,
        "match_score": (
            min(30.0, 15.0 + len(matched_terms) * 5.0)
            if match_level == "strong"
            else min(20.0, 10.0 + len(matched_terms) * 3.0)
            if match_level == "candidate"
            else 0.0
        ),
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
        "template_strongly_satisfied": satisfied,
        "template_match_level": "strong" if satisfied else "none",
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
    candidate_type = claim_type in {
        "detailed_comparison",
        "performance_comparison",
        "method_summary",
        "capability_summary",
        "ordinary_reference",
    }
    strong = (
        not guard_failure
        and candidate_type
        and has_comparison
        and has_detail
        and (sentence_count >= 2 or len(evidence_context or "") >= 220)
    )
    candidate = (
        not guard_failure
        and candidate_type
        and has_comparison
        and not strong
    )
    satisfied = strong or candidate
    if guard_failure:
        failure = guard_failure
    elif not candidate_type:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif not has_comparison:
        failure = "no explicit comparison expression in body text"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=satisfied,
        reason=(
            "target-anchored substantive comparison with concrete details"
            if strong
            else "target-anchored comparison candidate; detail or metric support requires review"
        ),
        failure=failure,
        matched_terms=(
            ["comparison", "concrete comparison detail"]
            if strong
            else ["comparison candidate"]
            if candidate
            else []
        ),
        match_level="strong" if strong else "candidate",
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
    candidate_type = claim_type in {
        "baseline_or_benchmark",
        "performance_comparison",
        "method_summary",
        "ordinary_reference",
    }
    strong = (
        not guard_failure
        and candidate_type
        and has_baseline
        and has_evaluation
    )
    candidate = (
        not guard_failure
        and candidate_type
        and has_baseline
        and not strong
    )
    satisfied = strong or candidate
    if guard_failure:
        failure = guard_failure
    elif not candidate_type:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif not has_baseline:
        failure = "target paper is not explicitly used as a baseline or benchmark"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=satisfied,
        reason=(
            "target paper is explicitly used as an evaluated baseline or benchmark"
            if strong
            else "target paper is described as a baseline or benchmark candidate; experimental use requires review"
        ),
        failure=failure,
        matched_terms=(
            ["baseline or benchmark", "evaluation context"]
            if strong
            else ["baseline or benchmark candidate"]
            if candidate
            else []
        ),
        match_level="strong" if strong else "candidate",
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
            r"\b(effective\w*|demonstrat\w*|accurate|robust|valuable|significant|important|promising|"
            r"novel|strong|superior|outperform\w*|improv\w*|efficien\w*|"
            r"enhanc\w*|mitigat\w*|reduc\w*|accelerat\w*|facilitat\w*|"
            r"success\w*|high[- ]precision|"
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
    has_substantive_description = (
        _has_method_or_capability_statement(citation_text)
        or _has_substantive_action(citation_text)
    )
    candidate_type = claim_type in allowed_types or claim_type in {
        "ordinary_reference",
        "method_use",
    }
    strong = (
        not guard_failure
        and candidate_type
        and has_positive_language
        and not has_limitation
    )
    candidate = (
        not guard_failure
        and candidate_type
        and has_substantive_description
        and not has_limitation
        and not strong
    )
    satisfied = strong or candidate
    if guard_failure:
        failure = guard_failure
    elif not candidate_type:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif has_limitation:
        failure = "limitation feedback cannot satisfy positive evaluation"
    elif not has_substantive_description and not has_positive_language:
        failure = "no target-specific capability, contribution, effect, or value statement"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=satisfied,
        reason=(
            "explicit target-anchored positive evaluation in body text"
            if strong
            else "target-anchored method or capability description is a positive-evaluation candidate"
        ),
        failure=failure,
        matched_terms=(
            ["explicit positive evaluation"]
            if strong
            else ["target-specific capability candidate"]
            if candidate
            else []
        ),
        match_level="strong" if strong else "candidate",
    )


def _evaluate_limitation_template(
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
    claim_type = str(finding_payload.get("claim_type") or "")
    allowed_types = set(
        TEMPLATE_CONTRACTS["limitation_or_negative"]["allowed_evidence_types"]
    )
    quote_has_limitation = bool(
        re.search(
            r"\b(limitation|limited|less practical|impractical|not practical|"
            r"drawback|weakness|insufficient|fails? to|cannot|can only|"
            r"requires? pre[- ]install\w*|constraint|shortcoming)\b|"
            r"(局限|不足|受限|不实用|只能|无法|缺点)",
            citation_text,
            re.I,
        )
    )
    context_has_limitation = bool(
        re.search(
            r"\b(limitation|limited|less practical|impractical|not practical|"
            r"drawback|weakness|insufficient|fails? to|cannot|can only|"
            r"requires? pre[- ]install\w*|constraint|shortcoming)\b|"
            r"(局限|不足|受限|不实用|只能|无法|缺点)",
            evidence_context,
            re.I,
        )
    )
    strong = (
        not guard_failure
        and claim_type in allowed_types
        and quote_has_limitation
    )
    candidate = (
        not guard_failure
        and claim_type in allowed_types
        and context_has_limitation
        and not strong
    )
    if guard_failure:
        failure = guard_failure
    elif claim_type not in allowed_types:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif not quote_has_limitation and not context_has_limitation:
        failure = "no explicit target-specific limitation or negative evaluation"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=strong or candidate,
        reason=(
            "target-anchored body evidence explicitly states a limitation or practical constraint"
            if strong
            else "the surrounding target context contains a limitation that requires scope review"
        ),
        failure=failure,
        matched_terms=(
            ["explicit limitation or negative evaluation"]
            if strong
            else ["contextual limitation candidate"]
            if candidate
            else []
        ),
        match_level="strong" if strong else "candidate",
    )


def _evaluate_theoretical_foundation_template(
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
        TEMPLATE_CONTRACTS["theoretical_foundation"]["allowed_evidence_types"]
    )
    has_theory_terms = bool(
        re.search(
            r"\b(theor\w*|foundation|model|equation|formula|deriv\w*|"
            r"framework|mechanism|phase|frequency|particle[- ]filter|"
            r"based\s+on|builds?\s+on|following|integrat\w*)\b|"
            r"(理论|模型|公式|推导|机制|基础)",
            text,
            re.I,
        )
    )
    has_explicit_dependency = bool(
        re.search(
            r"\b(theoretical\s+foundation|derive[sd]?\s+from|builds?\s+on|"
            r"following|based\s+on|adopt\w*|integrat\w*|extend\w*)\b|"
            r"(理论基础|基于|沿用|采用|推导自)",
            text,
            re.I,
        )
    )
    strong = (
        not guard_failure
        and claim_type in allowed_types
        and has_theory_terms
        and has_explicit_dependency
    )
    candidate = (
        not guard_failure
        and claim_type in allowed_types
        and has_theory_terms
        and not strong
    )
    satisfied = strong or candidate
    if guard_failure:
        failure = guard_failure
    elif claim_type not in allowed_types:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif not has_theory_terms:
        failure = "no target-specific model, theory, equation, mechanism, or derivation statement"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=satisfied,
        reason=(
            "target paper is explicitly used as a theoretical or methodological foundation"
            if strong
            else "target-anchored model or mechanism description is a theoretical-foundation candidate"
        ),
        failure=failure,
        matched_terms=(
            ["explicit theoretical dependency"]
            if strong
            else ["model or mechanism candidate"]
            if candidate
            else []
        ),
        match_level="strong" if strong else "candidate",
    )


def _evaluate_method_foundation_template(
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
    claim_type = str(finding_payload.get("claim_type") or "")
    allowed_types = set(
        TEMPLATE_CONTRACTS["method_foundation"]["allowed_evidence_types"]
    )
    text = f"{citation_text} {evidence_context}"
    has_method_description = (
        _has_method_or_capability_statement(citation_text)
        or _has_substantive_action(citation_text)
    )
    has_explicit_dependency = bool(
        re.search(
            r"\b(adopt\w*|use[sd]?|utiliz\w*|follow\w*|builds?\s+on|"
            r"based\s+on|according\s+to|derive[sd]?\s+from|extend\w*|"
            r"implement\w*|reuse\w*|leverag\w*)\b|"
            r"(采用|沿用|基于|依据|源自|扩展|复现|使用)",
            text,
            re.I,
        )
    )
    strong = (
        not guard_failure
        and claim_type in allowed_types
        and claim_type != "method_summary"
        and has_method_description
        and has_explicit_dependency
    )
    candidate = (
        not guard_failure
        and claim_type in allowed_types
        and has_method_description
        and not strong
    )
    if guard_failure:
        failure = guard_failure
    elif claim_type not in allowed_types:
        failure = f"evidence type {claim_type or 'unknown'} is not allowed by the template"
    elif not has_method_description:
        failure = "no concrete target-specific method description"
    else:
        failure = ""
    return _template_evaluation(
        template,
        satisfied=strong or candidate,
        reason=(
            "the citing paper explicitly adopts or builds on the target paper's method"
            if strong
            else "the body describes a concrete target method, but adoption or dependency requires review"
        ),
        failure=failure,
        matched_terms=(
            ["explicit method adoption or dependency"]
            if strong
            else ["concrete method summary"]
            if candidate
            else []
        ),
        match_level="strong" if strong else "candidate",
    )


def _effective_rules(template: AnalysisTemplate) -> dict:
    rules = _load_json_object(template.scoring_rules_json)
    contract = TEMPLATE_CONTRACTS.get(template.template_type, {})
    effective = dict(contract)
    effective.update(rules)
    if not effective.get("allowed_evidence_types") and contract.get(
        "allowed_evidence_types"
    ):
        effective["allowed_evidence_types"] = list(
            contract["allowed_evidence_types"]
        )
    if not effective.get("strict_rules") and contract.get("strict_rules"):
        effective["strict_rules"] = list(contract["strict_rules"])
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
    has_direct_anchor = _has_target_anchor(
        citation_text,
        target_reference_marker,
        cited_paper_title,
    )
    has_safe_inherited_anchor = bool(
        finding_payload.get("target_anchor_inherited", False)
    )
    if (
        bool(rules.get("require_target_marker", False))
        and not has_direct_anchor
        and not has_safe_inherited_anchor
    ):
        return "citation_text does not anchor to target paper"
    return ""


def _template_evaluation(
    template: AnalysisTemplate,
    *,
    satisfied: bool,
    reason: str,
    failure: str,
    matched_terms: List[str],
    match_level: str = "strong",
) -> dict:
    normalized_level = match_level if satisfied else "none"
    return {
        "template_id": template.id,
        "template_name": template.description or template.name,
        "template_type": template.template_type,
        "template_satisfied": satisfied,
        "template_strongly_satisfied": satisfied and normalized_level == "strong",
        "template_match_level": normalized_level,
        "template_match_reason": reason if satisfied else "",
        "template_failure_reason": failure,
        "matched_terms": matched_terms,
        "match_score": (
            30.0
            if normalized_level == "strong"
            else 15.0
            if normalized_level == "candidate"
            else 0.0
        ),
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
            r"\b(achiev\w*|demonstrat\w*|detect\w*|measur\w*|estimat\w*|captur\w*|"
            r"enable\w*|use[sd]?|using|adopt\w*|extend\w*|compar\w*|"
            r"outperform\w*|improv\w*|reconstruct\w*|extract\w*|"
            r"distinguish\w*)\b",
            citation_text or "",
            flags=re.I,
        )
    )


def _has_method_or_capability_statement(text: str) -> bool:
    return bool(
        re.search(
            r"\b(propos\w*|present\w*|introduc\w*|develop\w*|design\w*|"
            r"utiliz\w*|use[sd]?|using|achiev\w*|enable\w*|detect\w*|"
            r"measur\w*|estimat\w*|implement\w*|extend\w*|improv\w*|captur\w*|"
            r"reconstruct\w*|extract\w*|distinguish\w*)\b",
            text or "",
            flags=re.I,
        )
        or bool(
            re.search(
                r"(提出|介绍|设计|实现|采用|使用|扩展|改进|检测|测量|捕获|重建)"
                r".{0,40}(方法|机制|系统|能力|贡献|模型)",
                text or "",
            )
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

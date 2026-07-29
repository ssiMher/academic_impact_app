"""Evidence interpretation for report-ready citation claims.

This layer turns a raw StrongEvidence quote plus context into a cautious,
auditable report statement. It intentionally separates what the quote supports
from what it does not support.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional


@dataclass
class EvidenceInterpretation:
    evidence_claim_zh: str
    judgment_basis_zh: str
    limitation_zh: str
    copy_ready_statement_zh: str
    confidence_level: str
    report_recommendation: str
    judgment_label: str
    key_phrases: List[str]
    risk_note: str


def interpret_evidence(
    *,
    evidence_quote: str,
    evidence_context: str,
    card_type: str,
    evidence_type: str,
    stance: str,
    mention_type: str,
    citing_paper_title: str,
    cited_paper_title: str,
    section_heading: str = "",
    target_reference_marker: str = "",
    key_phrases: Optional[List[str]] = None,
    template_match_reason: str = "",
    template_satisfied: Optional[bool] = None,
    template_failure_reason: str = "",
    anchor_validation_status: str = "unknown",
    anchor_validation_reason: str = "",
    evidence_strength: str = "",
) -> EvidenceInterpretation:
    key_phrases = _dedupe([str(item).strip() for item in (key_phrases or []) if str(item).strip()])
    combined = f"{evidence_quote} {evidence_context}"
    key_phrases = _dedupe([*key_phrases, *_extract_terms(combined)])
    if anchor_validation_status == "invalid":
        return _invalid_anchor_interpretation(
            evidence_quote=evidence_quote,
            anchor_validation_reason=anchor_validation_reason,
            key_phrases=key_phrases,
        )

    rfid_kind = _rfid_kind(
        evidence_quote=evidence_quote,
        evidence_context=evidence_context,
        template_match_reason=template_match_reason,
        template_satisfied=template_satisfied,
        template_failure_reason=template_failure_reason,
        stance=stance,
        card_type=card_type,
    )
    if rfid_kind:
        return _rfid_interpretation(
            rfid_kind=rfid_kind,
            evidence_quote=evidence_quote,
            evidence_context=evidence_context,
            citing_paper_title=citing_paper_title,
            cited_paper_title=cited_paper_title,
            target_reference_marker=target_reference_marker,
            key_phrases=key_phrases,
            mention_type=mention_type,
        )

    first_kind = _first_scope_kind(
        evidence_quote=evidence_quote,
        template_match_reason=template_match_reason,
        template_satisfied=template_satisfied,
        template_failure_reason=template_failure_reason,
    )
    if first_kind:
        return _first_interpretation(
            first_kind=first_kind,
            evidence_quote=evidence_quote,
            citing_paper_title=citing_paper_title,
            cited_paper_title=cited_paper_title,
            target_reference_marker=target_reference_marker,
            key_phrases=key_phrases,
        )

    return _generic_interpretation(
        evidence_quote=evidence_quote,
        evidence_context=evidence_context,
        card_type=card_type,
        evidence_type=evidence_type,
        stance=stance,
        mention_type=mention_type,
        citing_paper_title=citing_paper_title,
        cited_paper_title=cited_paper_title,
        section_heading=section_heading,
        target_reference_marker=target_reference_marker,
        key_phrases=key_phrases,
        evidence_strength=evidence_strength,
    )


def _invalid_anchor_interpretation(
    *,
    evidence_quote: str,
    anchor_validation_reason: str,
    key_phrases: List[str],
) -> EvidenceInterpretation:
    reason = anchor_validation_reason or "target anchor validation failed"
    return EvidenceInterpretation(
        evidence_claim_zh="该候选证据的引用锚点与目标论文不匹配，不能作为目标论文的有效佐证。",
        judgment_basis_zh=f"系统检测到原文证据没有可靠指向目标论文，锚点校验原因：{reason}。",
        limitation_zh="不能把引用其他编号、其他方法或其他论文的句子归因给当前目标论文。",
        copy_ready_statement_zh="该候选证据因引用编号或目标锚点不匹配，建议从正式报告中排除，仅保留为误报诊断材料。",
        confidence_level="low",
        report_recommendation="不建议纳入",
        judgment_label="误报候选",
        key_phrases=key_phrases,
        risk_note="锚点不匹配，默认不纳入报告。",
    )


def _rfid_interpretation(
    *,
    rfid_kind: str,
    evidence_quote: str,
    evidence_context: str,
    citing_paper_title: str,
    cited_paper_title: str,
    target_reference_marker: str,
    key_phrases: List[str],
    mention_type: str,
) -> EvidenceInterpretation:
    marker_text = f"并通过 {target_reference_marker} 锚定目标论文" if target_reference_marker else "并锚定目标论文"
    quote_terms = _join(key_phrases)
    grouped_note = "该句属于成组引用，归因范围需要人工复核。" if mention_type == "grouped_citation" else ""
    if rfid_kind == "direct_submm":
        claim = "原文明确把目标论文与 sub-mm / submillimeter / millimeter-level 等精度或能力表述关联起来。"
        basis = f"证据句 {marker_text}，且出现了 {quote_terms or '亚毫米/毫米级相关表述'}，因此可作为直接亚毫米级能力佐证。"
        limitation = "该证据只能说明原文明确支持的精度/能力范围，不能额外推断未出现的应用场景或性能指标。"
        recommendation = "推荐纳入"
        confidence = "high"
    elif rfid_kind == "loudspeaker_vibration":
        claim = "原文确认目标论文与 RFID 扬声器/声学振动感知能力相关。"
        basis = f"证据句 {marker_text}，并出现了 {quote_terms or 'RFID 与 vibration/speaker/acoustic sensing 相关短语'}；但未明确出现 sub-mm 时，不应写成直接亚毫米精度佐证。"
        limitation = "可以表述为 RFID 振动/声学感知能力佐证；如果原文没有 sub-mm 等词，不应声称其证明亚毫米级精度。"
        recommendation = "推荐纳入"
        confidence = "medium"
    elif rfid_kind == "through_wall":
        claim = "原文确认目标论文与 RFID 穿墙窃听或 through-wall sensing 能力相关。"
        basis = f"证据句 {marker_text}，并出现了 {quote_terms or 'through-wall / eavesdropping 相关短语'}，可作为穿墙窃听能力相关佐证。"
        limitation = "该证据不等同于精度评价；除非原文同时出现精度词，否则不能写成亚毫米级能力佐证。"
        recommendation = "候选复核"
        confidence = "medium"
    elif rfid_kind == "limitation":
        claim = "原文提供的是 RFID 相关方法的局限性或负面反馈。"
        basis = f"证据句 {marker_text}，但语义指向 limitation/constraint/trade-off 等局限性表达。"
        limitation = "不能把该证据包装成正向亮点，只适合作为客观技术反馈或风险分析。"
        recommendation = "候选复核"
        confidence = "medium"
    elif rfid_kind == "plain_related":
        claim = "原文只是把目标论文列为 RFID 相关工作或普通背景引用。"
        basis = f"证据句虽然 {marker_text}，但没有明确 sub-mm、振动能力、穿墙窃听能力或方法采用表述。"
        limitation = "不能写成高度评价，也不能写成亚毫米级精度佐证或能力认可。"
        recommendation = "候选复核"
        confidence = "low"
    else:
        claim = "该 RFID 模板候选没有足够正文证据支持模板命中。"
        basis = "模板相关词没有明确作用到目标论文，或缺少正文锚点。"
        limitation = "不能凭模板关键词或系统知识补写亚毫米级、振动感知等结论。"
        recommendation = "不建议纳入"
        confidence = "low"
    risk = grouped_note or ("这是模板相关候选，仍需人工核对原文锚点和作用范围。" if recommendation != "推荐纳入" else "")
    statement = f"《{citing_paper_title}》引用《{cited_paper_title}》时，{claim}{limitation if recommendation != '推荐纳入' else ''}"
    return EvidenceInterpretation(
        evidence_claim_zh=claim,
        judgment_basis_zh=basis + (f" {grouped_note}" if grouped_note else ""),
        limitation_zh=limitation,
        copy_ready_statement_zh=statement,
        confidence_level=confidence,
        report_recommendation=recommendation,
        judgment_label={
            "direct_submm": "直接亚毫米能力佐证",
            "loudspeaker_vibration": "RFID 振动能力佐证",
            "through_wall": "穿墙窃听能力佐证",
            "limitation": "局限性反馈",
            "plain_related": "普通相关工作",
        }.get(rfid_kind, "模板未满足"),
        key_phrases=key_phrases,
        risk_note=risk,
    )


def _first_interpretation(
    *,
    first_kind: str,
    evidence_quote: str,
    citing_paper_title: str,
    cited_paper_title: str,
    target_reference_marker: str,
    key_phrases: List[str],
) -> EvidenceInterpretation:
    if first_kind == "satisfied":
        basis = f"原文中的 first / pioneering / seminal 等表述明确作用到目标论文{f'（{target_reference_marker}）' if target_reference_marker else ''}。"
        return EvidenceInterpretation(
            evidence_claim_zh="原文明确将目标论文描述为首次、开创性或先导性工作。",
            judgment_basis_zh=basis,
            limitation_zh="只能按原文作用域表述，不能扩展为所有方向或所有任务的首次。",
            copy_ready_statement_zh=f"《{citing_paper_title}》在正文中明确以首次/开创性相关表述评价《{cited_paper_title}》，可作为先导性影响的第三方佐证；表述范围应严格限定在原文上下文。",
            confidence_level="high",
            report_recommendation="推荐纳入",
            judgment_label="首次/开创性明确佐证",
            key_phrases=key_phrases,
            risk_note="需确认 first/pioneering 的语法作用域确实指向目标论文。",
        )
    return EvidenceInterpretation(
        evidence_claim_zh="原文出现 first/pioneering 相关词，但作用对象不是目标论文或作用域不清。",
        judgment_basis_zh="first/pioneering 词没有与目标引用编号、标题或方法名建立足够近的语义锚点。",
        limitation_zh="不能因为句子中出现 first 等词，就把该词归因给目标论文。",
        copy_ready_statement_zh="该候选不宜作为首次/开创性佐证纳入报告，建议仅作为调试或人工复核材料。",
        confidence_level="low",
        report_recommendation="不建议纳入",
        judgment_label="首次作用域不明确",
        key_phrases=key_phrases,
        risk_note="first/pioneering 作用域不清或指向其他工作。",
    )


def _generic_interpretation(
    *,
    evidence_quote: str,
    evidence_context: str,
    card_type: str,
    evidence_type: str,
    stance: str,
    mention_type: str,
    citing_paper_title: str,
    cited_paper_title: str,
    section_heading: str,
    target_reference_marker: str,
    key_phrases: List[str],
    evidence_strength: str,
) -> EvidenceInterpretation:
    marker = f"正文包含目标引用编号 {target_reference_marker}，" if target_reference_marker else ""
    terms = _join(key_phrases) or "原文关键表述"
    section_label = "Related Work" if "related work" in (section_heading or "").lower() else section_heading
    section = f"位于“{section_label}”上下文中，" if section_label else ""
    grouped = mention_type == "grouped_citation"
    negative = stance in {"negative", "mixed"} or card_type == "limitation_or_negative"
    ordinary = card_type in {"representative_work", "background_reference", "ordinary_citation", "weak_mention", "citation_only"}
    if negative:
        label = "局限性/负面反馈"
        claim = "原文表达的是局限性、负面比较或技术约束反馈。"
        limitation = "不能改写成正向亮点或高度认可；适合用于客观评价或局限性分析。"
        recommendation = "候选复核"
        confidence = "medium"
    elif ordinary:
        label = "普通相关工作引用" if card_type != "representative_work" else "代表性相关工作"
        claim = "原文说明目标论文被纳入相关工作或技术脉络。"
        limitation = "不能写成高度评价，也不宜表述为高度评价、方法采用或性能认可，除非原文另有明确支持。"
        recommendation = "候选复核"
        confidence = "low" if evidence_strength in {"weak", "low"} else "medium"
    elif card_type == "theoretical_foundation":
        label = "理论基础"
        claim = "原文显示目标论文被用于理论推导或理论建模。"
        limitation = "只能表述为原文上下文中的理论基础或建模依据，不能扩展为所有后续工作的通用基础。"
        recommendation = "推荐纳入" if evidence_strength in {"strong", "moderate"} and not grouped else "候选复核"
        confidence = "high" if recommendation == "推荐纳入" else "medium"
    elif card_type == "application_extension":
        label = "应用拓展"
        claim = "原文显示目标论文的方法或思想被用于新的应用场景。"
        limitation = "只能说明该引用论文中的应用拓展关系，不能自动证明更广泛的产业或跨领域影响。"
        recommendation = "推荐纳入" if evidence_strength in {"strong", "moderate"} and not grouped else "候选复核"
        confidence = "high" if recommendation == "推荐纳入" else "medium"
    else:
        label = _label_for_card(card_type)
        claim = f"原文支持“{label}”这一证据判断。"
        limitation = "表述应限定在原文上下文和引用锚点范围内，不能扩展到原文没有支持的评价。"
        recommendation = "推荐纳入" if evidence_strength in {"strong", "moderate"} and not grouped else "候选复核"
        confidence = "high" if recommendation == "推荐纳入" else "medium"
    risk_parts = []
    if grouped:
        risk_parts.append("成组引用，归因需复核。")
    if ordinary:
        risk_parts.append("不是直接正向评价，不应包装成高度评价。")
    if negative:
        risk_parts.append("负面/局限性证据不能放入亮点评价栏目。")
    basis = f"{section}{marker}并围绕 {terms} 展开表述，因此支持“{label}”判断。"
    if grouped:
        basis += " 但该句属于成组引用，不能自动断言全部评价唯一归属给目标论文。"
    if ordinary:
        basis += " 原文没有给出高度赞扬。"
    statement = f"《{citing_paper_title}》在正文中引用《{cited_paper_title}》，{claim}{limitation}"
    return EvidenceInterpretation(
        evidence_claim_zh=claim,
        judgment_basis_zh=basis,
        limitation_zh=limitation,
        copy_ready_statement_zh=statement,
        confidence_level=confidence,
        report_recommendation=recommendation,
        judgment_label=label,
        key_phrases=key_phrases,
        risk_note=" ".join(risk_parts),
    )


def _rfid_kind(
    *,
    evidence_quote: str,
    evidence_context: str,
    template_match_reason: str,
    template_satisfied: Optional[bool],
    template_failure_reason: str,
    stance: str,
    card_type: str,
) -> Optional[str]:
    template_text = _norm(f"{template_match_reason} {template_failure_reason}")
    haystack = _norm(f"{evidence_quote} {evidence_context} {template_match_reason} {template_failure_reason}")
    has_rfid_template = "rfid" in template_text or "亚毫米" in template_text or "sub-mm" in template_text or "submillimeter" in template_text
    if not has_rfid_template:
        return None
    if stance in {"negative", "mixed"} or card_type == "limitation_or_negative" or _contains_any(haystack, ["limitation", "limited", "constraint", "trade-off", "tradeoff", "sensitive to", "shortcoming"]):
        return "limitation"
    if not template_satisfied:
        if "plain rfid reference" in haystack or "related work" in haystack:
            return "plain_related"
        return "mismatch"
    if _contains_any(haystack, ["sub-mm", "sub mm", "submillimeter", "sub-millimeter", "millimeter-level", "mm-level"]):
        return "direct_submm"
    if _contains_any(haystack, ["through-wall", "through wall", "eavesdropping"]):
        return "through_wall"
    if _contains_any(haystack, ["loudspeaker vibration", "speaker vibration", "vibration sensing", "acoustic sensing", "voice sensing", "audio sensing"]):
        return "loudspeaker_vibration"
    return "plain_related"


def _first_scope_kind(
    *,
    evidence_quote: str,
    template_match_reason: str,
    template_satisfied: Optional[bool],
    template_failure_reason: str,
) -> Optional[str]:
    quote = _norm(evidence_quote)
    first_terms = [
        "first",
        "pioneering",
        "seminal",
        "earliest",
        "首次",
        "开创性",
        "率先",
        "最早",
    ]
    if not _contains_any(quote, first_terms):
        return None
    if template_satisfied and _contains_any(
        _norm(template_match_reason),
        first_terms,
    ):
        return "satisfied"
    return "scope_unclear"


def _extract_terms(text: str) -> List[str]:
    patterns = [
        r"\bsub[-\s]?mm\b",
        r"\bsub[-\s]?millimeter(?:-level)?\b",
        r"\bmillimeter[-\s]?level\b",
        r"\bmm[-\s]?level\b",
        r"\bRFID(?:\s+tag)?\b",
        r"\bvibration\s+sensing\b",
        r"\b(?:loudspeaker|speaker|voice|audio|acoustic|tiny|micro)[-\s]vibration\b",
        r"\bthrough[-\s]wall\b",
        r"\beavesdropping\b",
        r"\b(?:[A-Za-z][\w'’-]{2,}\s+){1,4}(?:model|method|mechanism|process|operation|sensing|comparison|limitation|constraint|trade[-\s]?off|framework|system)\b",
    ]
    terms: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            terms.append(match.group(0).strip())
    return _dedupe(terms)[:8]


def _label_for_card(card_type: str) -> str:
    return {
        "theoretical_foundation": "理论基础",
        "method_foundation": "方法采用",
        "application_extension": "应用拓展",
        "detailed_comparison": "详细对比",
        "baseline_or_benchmark": "基线/Benchmark",
        "positive_evaluation": "正向评价",
        "representative_work": "代表性相关工作",
        "first_or_seminal_claim": "首次/开创性",
    }.get(card_type, card_type.replace("_", " "))


def _join(items: List[str]) -> str:
    return "、".join(_dedupe(items)[:5])


def _dedupe(items: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        value = str(item or "").strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _contains_any(text: str, needles: List[str]) -> bool:
    return any(needle in text for needle in needles)


def _norm(value: str) -> str:
    return " ".join((value or "").replace("–", "-").replace("—", "-").lower().split())

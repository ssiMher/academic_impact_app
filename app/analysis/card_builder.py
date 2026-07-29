"""Build deterministic highlight card drafts from StrongEvidence."""

from __future__ import annotations

import json
import re
from typing import Dict, Optional

from app.analysis.evidence_interpretation import interpret_evidence
from app.models import DeepAnalysisQueueItem, NotableAuthor, StrongEvidence


CARD_TYPE_BY_ASPECT: Dict[str, str] = {
    "positive_evaluation": "positive_evaluation",
    "representative_work": "representative_work",
    "first_or_seminal_claim": "first_or_seminal_claim",
    "detailed_comparison": "detailed_comparison",
    "baseline_or_benchmark": "baseline_or_benchmark",
    "theoretical_foundation": "theoretical_foundation",
    "method_foundation": "method_foundation",
    "application_extension": "application_extension",
    "important_author_citation": "important_author_citation",
    "long_context_citation": "long_context_citation",
}

NEGATIVE_STANCES = {"negative", "mixed"}


def card_type_for_evidence(evidence: StrongEvidence) -> str:
    if evidence.stance in NEGATIVE_STANCES and evidence.aspect not in {
        "detailed_comparison",
        "baseline_or_benchmark",
    }:
        return "limitation_or_negative"
    if (
        evidence.stance == "neutral"
        and evidence.aspect == "custom_template_evidence"
    ):
        return "neutral_evaluation"
    return CARD_TYPE_BY_ASPECT.get(evidence.aspect or "", "positive_evaluation")


def build_card_values(
    *,
    evidence: StrongEvidence,
    item: DeepAnalysisQueueItem,
    sort_order: int,
    context_preview: Optional[dict] = None,
    notable_author: Optional[NotableAuthor] = None,
) -> dict:
    card_type = card_type_for_evidence(evidence)
    source_title = item.citing_paper_title
    cited_title = item.cited_paper_title
    narrative = generate_impact_narrative(
        evidence=evidence,
        item=item,
        card_type=card_type,
        context_preview=context_preview or {},
        notable_author=notable_author,
    )
    title = narrative["title_zh"] or _title_for(card_type, cited_title, notable_author)
    subtitle = _subtitle_for(card_type, source_title, item.venue, item.year, notable_author)
    if evidence.review_status == "unreviewed" and evidence.evidence_strength == "strong":
        subtitle = f"Draft card - {subtitle}"
    citing_authors = _load_json_list(item.citing_authors_json)
    include_in_report = evidence.aspect not in {"background_reference"}
    if card_type in {"ordinary_citation", "background_reference", "weak_mention", "citation_only"}:
        include_in_report = False
    return {
        "scholar_session_id": evidence.scholar_session_id,
        "strong_evidence_id": evidence.id,
        "card_type": card_type,
        "title": title,
        "subtitle": subtitle,
        "narrative_zh": narrative["narrative_zh"],
        "narrative_en": None,
        "body_markdown": narrative["narrative_zh"],
        "evidence_quote": evidence.citation_text or "",
        "highlighted_quote_html": evidence.highlighted_text_html,
        "source_citing_paper_title": source_title,
        "source_cited_paper_title": cited_title,
        "citing_authors_json": json.dumps(citing_authors, ensure_ascii=False),
        "notable_author_name": notable_author.name if notable_author else None,
        "notable_author_affiliation": notable_author.affiliation if notable_author else None,
        "notable_author_role": "重要作者" if notable_author else None,
        "fellow_status": notable_author.fellow_status if notable_author else "unknown",
        "venue": item.venue,
        "venue_tier": item.venue_tier,
        "aspect": evidence.aspect,
        "stance": evidence.stance,
        "evidence_strength": evidence.evidence_strength,
        "score": evidence.score,
        "source_evidence_id": evidence.id,
        "review_status": evidence.review_status,
        "sort_order": sort_order,
        "user_note": evidence.user_note,
        "include_in_report": include_in_report,
    }


def generate_impact_narrative(
    *,
    evidence: StrongEvidence,
    item: DeepAnalysisQueueItem,
    card_type: str,
    context_preview: dict,
    notable_author: Optional[NotableAuthor] = None,
) -> dict:
    quote = (evidence.citation_text or "").strip()
    display_context = (
        context_preview.get("display_context")
        or context_preview.get("paragraph_context")
        or context_preview.get("anchor_context")
        or quote
    )
    section_heading = (context_preview.get("section_heading") or "").strip()
    target_marker = (context_preview.get("target_reference_marker") or "").strip()
    technical_terms = _extract_technical_terms(
        quote,
        display_context,
        context_preview=context_preview,
        evidence=evidence,
    )
    evidence_basis = _build_evidence_basis(section_heading, target_marker, technical_terms)
    title_zh = _title_for(card_type, item.cited_paper_title, notable_author)
    venue_year = _venue_year(item.venue, item.year)
    author_prefix = _author_prefix(notable_author)
    risk_note = _risk_note(card_type, evidence)
    anchor_status = context_preview.get("anchor_validation_status") or evidence.anchor_status or "unknown"
    anchor_reason = context_preview.get("anchor_validation_reason") or ""

    narrative = _narrative_zh(
        card_type=card_type,
        evidence=evidence,
        source_title=item.citing_paper_title,
        cited_title=item.cited_paper_title,
        venue_year=venue_year,
        section_heading=section_heading,
        target_marker=target_marker,
        technical_terms=technical_terms,
        evidence_basis=evidence_basis,
        author_prefix=author_prefix,
    )
    interpretation = interpret_evidence(
        evidence_quote=quote,
        evidence_context=display_context,
        card_type=card_type,
        evidence_type=evidence.aspect or card_type,
        stance=evidence.stance or "",
        mention_type=evidence.mention_type or "",
        citing_paper_title=item.citing_paper_title,
        cited_paper_title=item.cited_paper_title,
        section_heading=section_heading,
        target_reference_marker=target_marker,
        key_phrases=technical_terms,
        template_match_reason=evidence.template_match_reason or "",
        template_satisfied=evidence.template_satisfied,
        template_failure_reason=evidence.template_failure_reason or "",
        anchor_validation_status=anchor_status,
        anchor_validation_reason=anchor_reason,
        evidence_strength=evidence.evidence_strength or "",
    )
    judgment = build_judgment_output(
        evidence=evidence,
        item=item,
        card_type=card_type,
        evidence_quote=quote,
        evidence_context=display_context,
        section_heading=section_heading,
        target_marker=target_marker,
        technical_terms=technical_terms,
        narrative_zh=narrative,
        risk_note=risk_note,
        interpretation=interpretation,
    )
    narrative = _narrative_from_interpretation(interpretation)
    return {
        "title_zh": title_zh,
        "narrative_zh": narrative,
        "risk_note": interpretation.risk_note or risk_note,
        "recommended_report_section": _recommended_report_section(card_type),
        "technical_terms_used": interpretation.key_phrases or technical_terms,
        "evidence_basis": evidence_basis,
        "confidence": interpretation.confidence_level,
        "evidence_claim_zh": interpretation.evidence_claim_zh,
        "judgment_basis_zh": interpretation.judgment_basis_zh,
        "limitation_zh": interpretation.limitation_zh,
        "copy_ready_statement_zh": interpretation.copy_ready_statement_zh,
        "confidence_level": interpretation.confidence_level,
        "report_recommendation": interpretation.report_recommendation,
        **judgment,
    }


def build_judgment_output(
    *,
    evidence: StrongEvidence,
    item: DeepAnalysisQueueItem,
    card_type: str,
    evidence_quote: str,
    evidence_context: str,
    section_heading: str,
    target_marker: str,
    technical_terms: list[str],
    narrative_zh: str,
    risk_note: str,
    interpretation=None,
) -> dict:
    if interpretation is not None:
        return {
            "evidence_quote": evidence_quote,
            "evidence_context": evidence_context,
            "key_phrases": interpretation.key_phrases,
            "judgment_label": interpretation.judgment_label,
            "why_this_judgment": interpretation.judgment_basis_zh,
            "copy_ready_statement": interpretation.copy_ready_statement_zh,
            "risk_note": interpretation.risk_note,
            "confidence": interpretation.confidence_level,
            "evidence_claim_zh": interpretation.evidence_claim_zh,
            "judgment_basis_zh": interpretation.judgment_basis_zh,
            "limitation_zh": interpretation.limitation_zh,
            "copy_ready_statement_zh": interpretation.copy_ready_statement_zh,
            "confidence_level": interpretation.confidence_level,
            "report_recommendation": interpretation.report_recommendation,
        }
    key_phrases = _dedupe_terms([*technical_terms, *_extract_precision_phrases(f"{evidence_quote} {evidence_context}")])[:8]
    judgment_label = _judgment_label(card_type, evidence)
    confidence = "medium" if evidence.evidence_strength in {"weak", "moderate"} else "high"
    why_parts = []
    if section_heading:
        why_parts.append(f"证据位于“{section_heading}”上下文中。")
    if target_marker:
        why_parts.append(f"原文包含目标引用编号 {target_marker}，可将该段与被引论文建立锚点关系。")
    if key_phrases:
        why_parts.append(f"原文中的关键短语包括：{' / '.join(key_phrases[:5])}。")
    why_parts.append(_judgment_reason_sentence(card_type, evidence))
    precision_terms = _extract_precision_phrases(f"{evidence_quote} {evidence_context}")
    if precision_terms:
        why_parts.append(f"若用于精度/传感能力佐证，原文明确出现：{' / '.join(precision_terms[:4])}。")
    if evidence.mention_type == "grouped_citation":
        why_parts.append("该证据来自成组引用，不能自动断言所有评价均唯一归属于目标论文。")

    copy_ready = _copy_ready_statement(
        item=item,
        card_type=card_type,
        narrative_zh=narrative_zh,
        risk_note=risk_note,
        precision_terms=precision_terms,
    )
    return {
        "evidence_quote": evidence_quote,
        "evidence_context": evidence_context,
        "key_phrases": key_phrases,
        "judgment_label": judgment_label,
        "why_this_judgment": "".join(why_parts),
        "copy_ready_statement": copy_ready,
        "risk_note": risk_note,
        "confidence": confidence,
    }


def _title_for(card_type: str, cited_title: str, notable_author: Optional[NotableAuthor]) -> str:
    if card_type == "limitation_or_negative":
        return f"局限性反馈：{cited_title}"
    if card_type == "representative_work":
        return f"代表性相关工作：{cited_title}"
    if card_type == "theoretical_foundation":
        return f"理论基础引用：{cited_title}"
    if card_type == "method_foundation":
        return f"方法采用引用：{cited_title}"
    if card_type == "ordinary_citation":
        return f"普通引用：{cited_title}"
    if card_type == "neutral_evaluation":
        return f"中性评价：{cited_title}"
    if notable_author and notable_author.fellow_status != "unknown":
        return f"{notable_author.name} 引用评价：{cited_title}"
    label = card_type.replace("_", " ").title()
    return f"{label}: {cited_title}"


def _narrative_from_interpretation(interpretation) -> str:
    basis = interpretation.judgment_basis_zh
    if len(basis) > 260:
        basis = basis[:260].rsplit("，", 1)[0] + "。"
    extra = ""
    if "局限性" in interpretation.judgment_label:
        extra += " 适合用于客观评价或局限性分析。"
    if "成组引用" in (interpretation.risk_note or ""):
        extra += " 需要人工确认归因范围。"
    return f"{interpretation.evidence_claim_zh}{basis}{extra}"


def _subtitle_for(
    card_type: str,
    source_title: str,
    venue: Optional[str],
    year: Optional[int],
    notable_author: Optional[NotableAuthor],
) -> str:
    venue_year = _venue_year(venue, year)
    if card_type == "limitation_or_negative":
        return f"客观技术反馈 / 来源论文：{source_title}{venue_year}"
    if card_type == "representative_work":
        return f"代表性相关工作 / 来源论文：{source_title}{venue_year}"
    if notable_author and notable_author.fellow_status != "unknown":
        return f"{notable_author.fellow_status} / {source_title}{venue_year}"
    return f"来源论文：{source_title}{venue_year}"


def _narrative_zh(
    *,
    card_type: str,
    evidence: StrongEvidence,
    source_title: str,
    cited_title: str,
    venue_year: str,
    section_heading: str,
    target_marker: str,
    technical_terms: list[str],
    evidence_basis: str,
    author_prefix: str,
) -> str:
    lead = f"{author_prefix}《{source_title}》"
    if venue_year:
        lead += venue_year
    section_intro = ""
    if section_heading:
        section_intro = f"在“{section_heading}”中"
    marker_text = f"通过 {target_marker} " if target_marker else ""

    if card_type == "theoretical_foundation":
        terms_text = _join_terms(technical_terms)
        if terms_text:
            detail = f"{marker_text}围绕 {terms_text} 展开建模/推导".strip()
        else:
            detail = f"{marker_text}将目标论文用于理论推导和模型解释".strip()
        return (
            f"{lead}{section_intro}{detail}。这说明《{cited_title}》中的相关方法或概念，"
            "被后续工作用于理论推导、模型解释或技术论证。"
        )

    if card_type == "method_foundation":
        method_terms = _join_terms(technical_terms)
        detail = f"，具体涉及 {method_terms}" if method_terms else ""
        return (
            f"{lead}{section_intro}{marker_text}将《{cited_title}》作为方法来源或方法基础{detail}，"
            "说明目标论文的技术路线已进入后续研究的方法链路。"
        )

    if card_type == "application_extension":
        return (
            f"{lead}{section_intro}{marker_text}将《{cited_title}》的方法或思想扩展到新的应用场景，"
            "说明该工作具有跨场景迁移价值。"
        )

    if card_type == "detailed_comparison":
        suffix = "该证据来自成组引用，需要人工确认归因范围。" if evidence.mention_type == "grouped_citation" else ""
        return (
            f"{lead}{section_intro}{marker_text}对《{cited_title}》所属方法进行了较为具体的比较，"
            "说明该工作已成为后续论文的实际对照对象。"
            f"{suffix}"
        ).strip()

    if card_type == "baseline_or_benchmark":
        return f"{lead}{section_intro}{marker_text}将《{cited_title}》作为 baseline 或 benchmark，说明该工作已成为该方向的代表性比较对象。"

    if card_type == "first_or_seminal_claim":
        return f"{lead}{section_intro}{marker_text}将《{cited_title}》描述为首次提出或开创性工作，说明其在该方向具有先导性影响。"

    if card_type == "limitation_or_negative":
        return (
            f"{lead}{section_intro}{marker_text}对《{cited_title}》或其所属方法提出了局限性反馈/负面比较，"
            "这类证据适合用于客观评价或局限性分析，不应包装成正向亮点。"
        )

    if card_type == "representative_work":
        route_terms = _join_terms(technical_terms)
        route_detail = f"，并提到 {route_terms}" if route_terms else ""
        intro = "在 Related Work 中将" if "related work" in (section_heading or "").lower() else f"{section_intro}将"
        return (
            f"{lead}{intro}《{cited_title}》纳入后续技术路线梳理{route_detail}。"
            "这说明目标论文已进入该方向的技术脉络，但原文没有给出直接性能评价或高度赞扬。"
        )

    if card_type == "positive_evaluation":
        return (
            f"{lead}{section_intro}{marker_text}对《{cited_title}》给出明确正向评价，"
            f"其依据来自 {evidence_basis or '正文原文表述'}，可作为亮点评价候选。"
        )

    if card_type == "neutral_evaluation":
        return (
            f"{lead}{section_intro}{marker_text}对《{cited_title}》作出事实性、中性描述，"
            "该证据适合用于说明后续论文如何概括目标工作的技术内容，不应改写为正向或负面评价。"
        )

    if card_type == "ordinary_citation":
        return (
            f"{lead}{section_intro}{marker_text}在正文中引用了《{cited_title}》，但当前上下文未显示明确的评价、方法采用或详细对比，"
            "建议人工复核后决定是否纳入汇报。"
        )

    if card_type == "background_reference":
        return (
            f"{lead}{section_intro}{marker_text}将《{cited_title}》作为背景相关工作引用。"
            "这类证据说明目标论文进入了技术脉络，但不等同于直接正向评价。"
        )

    if card_type == "citation_only":
        return f"{lead}{section_intro}出现了对《{cited_title}》的引用记录，但当前没有足够正文证据支持进一步亮点评价。"

    if card_type == "weak_mention":
        return (
            f"{lead}{section_intro}{marker_text}提到了《{cited_title}》，但现有上下文仍不足以支撑稳定的强证据判断，建议人工复核。"
        )

    return f"{lead}{marker_text}引用并讨论了《{cited_title}》，可作为后续人工整理汇报材料的依据。"


def _author_prefix(notable_author: Optional[NotableAuthor]) -> str:
    if notable_author and notable_author.fellow_status and notable_author.fellow_status != "unknown":
        return f"{notable_author.name}（{notable_author.fellow_status}）团队在"
    return ""


def _extract_technical_terms(
    citation_text: str,
    display_context: str,
    *,
    context_preview: dict,
    evidence: StrongEvidence,
) -> list[str]:
    terms: list[str] = []
    terms.extend(_load_json_list(evidence.highlight_keywords_json))
    terms.extend(str(term) for term in context_preview.get("highlight_terms", []) if str(term).strip())
    terms.extend(_extract_candidate_phrases(f"{citation_text} {display_context}", max_terms=8))
    return _dedupe_terms(terms)


def _build_evidence_basis(section_heading: str, target_marker: str, technical_terms: list[str]) -> str:
    parts = []
    if section_heading:
        parts.append(f"section={section_heading}")
    if target_marker:
        parts.append(f"marker={target_marker}")
    if technical_terms:
        parts.append("terms=" + ", ".join(technical_terms[:5]))
    return "; ".join(parts)


def _risk_note(card_type: str, evidence: StrongEvidence) -> str:
    notes = []
    if evidence.mention_type == "grouped_citation":
        notes.append("这是成组引用，需要人工确认归因范围。")
    if card_type in {"representative_work", "background_reference", "ordinary_citation", "citation_only", "weak_mention"}:
        notes.append("这不是直接正向评价，不应包装成高度评价。")
    if card_type == "limitation_or_negative":
        notes.append("这是局限性反馈/负面比较，不应改写成正向亮点。")
    return " ".join(notes)


def _judgment_label(card_type: str, evidence: StrongEvidence) -> str:
    label = _recommended_report_section(card_type)
    if evidence.mention_type == "grouped_citation":
        return f"{label}（成组引用待复核）"
    return label


def _judgment_reason_sentence(card_type: str, evidence: StrongEvidence) -> str:
    if card_type == "theoretical_foundation":
        return "因此判断为理论基础：该段不是单纯列出参考文献，而是在正文技术论述中把目标论文作为建模、推导或概念说明的依据。"
    if card_type == "method_foundation":
        return "因此判断为方法采用：该段将目标论文关联到后续方法设计、技术流程或实现依据。"
    if card_type == "representative_work":
        return "因此判断为代表性相关工作：该段体现目标论文被纳入相关工作或技术路线梳理，但不是直接高度评价。"
    if card_type == "limitation_or_negative":
        return "因此判断为局限性反馈：该段表达的是限制、负面比较或技术约束，不能改写成正向亮点。"
    if card_type in {"ordinary_citation", "background_reference", "citation_only", "weak_mention"}:
        return "因此判断为普通/背景引用：该段能证明正文引用存在，但不足以支持高度评价、方法采用或详细对比。"
    if evidence.stance == "positive":
        return "因此判断为正向证据：该段包含可追溯到原文的正向评价或使用依据。"
    return "该判断基于正文原文、引用锚点、证据类型和人工复核状态综合给出。"


def _copy_ready_statement(
    *,
    item: DeepAnalysisQueueItem,
    card_type: str,
    narrative_zh: str,
    risk_note: str,
    precision_terms: list[str],
) -> str:
    statement = narrative_zh
    if precision_terms:
        statement += f" 原文中可直接核验的相关表述包括“{' / '.join(precision_terms[:3])}”。"
    if card_type in {"representative_work", "background_reference", "ordinary_citation", "citation_only", "weak_mention"}:
        statement += " 该证据宜表述为相关工作引用或技术脉络引用，不宜表述为高度评价。"
    if risk_note:
        statement += f" 风险提示：{risk_note}"
    return statement


def _extract_precision_phrases(text: str) -> list[str]:
    patterns = [
        r"\bsub[-\s]?mm\b",
        r"\bsub[-\s]?millimeter(?:-level)?\b",
        r"\bmillimeter[-\s]?level\b",
        r"\bmillimetre[-\s]?level\b",
        r"\bmm[-\s]?level\b",
        r"\bvibration sensing\b",
        r"\bvibration[-\s]?based sensing\b",
        r"\bmicro[-\s]?vibration\b",
    ]
    phrases = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            phrases.append(match.group(0))
    return _dedupe_terms(phrases)


def _recommended_report_section(card_type: str) -> str:
    mapping = {
        "theoretical_foundation": "理论基础影响",
        "method_foundation": "方法采用",
        "representative_work": "代表性相关工作",
        "limitation_or_negative": "局限性反馈",
        "detailed_comparison": "详细对比",
        "baseline_or_benchmark": "基线与比较对象",
        "positive_evaluation": "正向评价",
        "neutral_evaluation": "中性评价",
        "ordinary_citation": "普通引用待复核",
        "background_reference": "背景引用待复核",
        "weak_mention": "弱证据待复核",
        "citation_only": "仅引用记录",
    }
    return mapping.get(card_type, "报告素材")


def _venue_year(venue: Optional[str], year: Optional[int]) -> str:
    parts = []
    if venue:
        parts.append(str(venue))
    if year:
        parts.append(str(year))
    return f"（{' / '.join(parts)}）" if parts else ""


def _join_terms(technical_terms: list[str]) -> str:
    return " / ".join(_dedupe_terms(technical_terms)[:5])


def _has_term(technical_terms: list[str], *terms: str) -> bool:
    lowered = {term.lower() for term in technical_terms}
    return any(term.lower() in lowered for term in terms)


def _extract_candidate_phrases(text: str, *, max_terms: int = 8) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "")
    if not cleaned:
        return []
    phrases: list[str] = []
    for match in re.finditer(r"\b(?:Eq\.?|Equation)\s*\(?\d+[A-Za-z]?\)?", cleaned, flags=re.IGNORECASE):
        phrases.append(match.group(0).strip())
    pattern = re.compile(
        r"\b(?:[^\W_][\w'’.-]{2,}\s+){1,5}"
        r"(?:model|models|method|methods|process|processes|operation|operations|"
        r"mechanism|mechanisms|equation|equations|framework|frameworks|"
        r"pipeline|pipelines|estimation|detection|tracking|classification|"
        r"vector|vectors|signal|signals|peak|peaks|difference|differences|"
        r"pattern|patterns|feature|features|representation|representations|"
        r"change|changes|sensor|sensors)\b",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(cleaned):
        phrase = match.group(0).strip(" ,.;:()[]")
        if 5 <= len(phrase) <= 90:
            phrases.append(phrase)
    return _dedupe_terms(phrases)[:max_terms]


def _dedupe_terms(terms: list[str]) -> list[str]:
    deduped: list[str] = []
    seen = set()
    for term in terms:
        cleaned = str(term or "").strip()
        normalized = cleaned.lower()
        if not cleaned or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)
    return deduped


def _load_json_list(value: Optional[str]):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []

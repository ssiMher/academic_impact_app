"""Service for built-in and custom analysis templates."""

import json
from typing import Iterable, List, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from app.analysis.template_matching import (
    build_custom_prompt_fragment,
    evaluate_templates_for_finding,
    format_template_snapshots_for_prompt,
    match_template_terms,
    template_snapshot,
)
from app.db.session import get_db
from app.models import AnalysisTemplate, DeepAnalysisQueueItem, FulltextAnalysisResult, HighlightCard, StrongEvidence, TemplateMatch
from app.repositories.template_repo import TemplateRepository


POSITIVE_EVALUATION_LEGACY_GOAL = "Find positive evaluations of the target paper."
POSITIVE_EVALUATION_GOAL = (
    "Judge whether the citing paper's body text gives a concrete account of the "
    "target paper's method, mechanism, capability, effect, or contribution. "
    "Explicit praise is not required. Ordinary listing, reference-only evidence, "
    "and evidence aligned to another paper do not satisfy this template."
)
POSITIVE_EVALUATION_LEGACY_PROMPT = (
    "Prioritize positive evaluation evidence grounded in citation_text."
)
POSITIVE_EVALUATION_PROMPT = (
    "Treat a concrete, target-anchored description of the cited paper's method, "
    "mechanism, capability, effect, or contribution as satisfying evidence even "
    "without praise words. Exclude ordinary lists, References entries, and "
    "misaligned citations."
)
POSITIVE_EVALUATION_LEGACY_STRICT_RULES = [
    "requires explicit positive evaluation of the target paper",
    "capability description alone is insufficient",
    "limitation feedback and ordinary related work are excluded",
]
POSITIVE_EVALUATION_ADVISORY_RULES = [
    "a concrete target-anchored method, mechanism, capability, effect, or contribution description may satisfy the template without praise words",
    "ordinary related-work listing and reference-only evidence are insufficient",
    "evidence aligned to another paper is invalid",
]


BUILTIN_TEMPLATES = [
    {
        "name": "first_or_pioneering_claim",
        "description": "首次/开创性明确表述",
        "template_type": "first_or_pioneering_claim",
        "goal": (
            "判断引用论文正文是否明确称目标论文为 first / pioneering / earliest / seminal / "
            "first-of-its-kind / for the first time / 首次 / 开创性。"
        ),
        "aspects": ["first_or_pioneering_claim", "first_or_seminal_claim"],
        "keywords": [
            "first",
            "the first",
            "pioneering",
            "earliest",
            "first-of-its-kind",
            "seminal",
            "for the first time",
            "首次",
            "开创性",
            "率先",
            "最早",
        ],
        "patterns": ["the first", "for the first time", "pioneering work", "seminal work"],
        "prompt": (
            "首次/开创性模板：只有正文原文明确出现 first/pioneering/seminal/earliest/"
            "for the first time 等表达时才判定满足；不得根据年份或引用量推断。"
        ),
        "rules": {
            "template_bonus": 30,
            "template_key": "first_or_pioneering_claim",
            "allowed_evidence_types": ["first_or_pioneering_claim", "first_or_seminal_claim"],
            "strict_rules": [
                "requires explicit first/pioneering expression in body text",
                "do not infer from publication year",
                "ordinary related work does not satisfy this template",
            ],
        },
    },
    {
        "name": "first_or_seminal_claim",
        "description": "首次/开创性评价",
        "template_type": "first_or_seminal_claim",
        "goal": "Find citations claiming the target paper was first, seminal, or pioneering.",
        "aspects": ["first_or_seminal_claim"],
        "keywords": ["first", "seminal", "pioneering", "首次", "开创"],
        "patterns": ["first work", "seminal work"],
        "prompt": "Prioritize claims that the target paper is first, seminal, or pioneering.",
        "rules": {
            "template_bonus": 20,
            "allowed_evidence_types": ["first_or_seminal_claim"],
            "strict_rules": [
                "requires explicit first/pioneering expression in body text",
                "expression must modify the target paper anchor",
            ],
            "require_target_marker": True,
            "allow_grouped_citation": False,
        },
    },
    {
        "name": "detailed_comparison",
        "description": "大篇幅对比",
        "template_type": "detailed_comparison",
        "goal": "Find detailed comparisons with the target paper.",
        "aspects": ["detailed_comparison"],
        "keywords": ["compare", "compared with", "comparison", "对比", "比较"],
        "patterns": ["compared with"],
        "prompt": "Prioritize detailed comparison evidence, not passing mentions.",
        "rules": {
            "template_bonus": 20,
            "allowed_evidence_types": [
                "detailed_comparison",
                "performance_comparison",
            ],
            "strict_rules": [
                "requires substantive multi-sentence or metric-backed comparison",
                "passing compared-with mention is insufficient",
            ],
            "require_target_marker": True,
            "allow_grouped_citation": False,
        },
    },
    {
        "name": "baseline_or_benchmark",
        "description": "作为 baseline / benchmark",
        "template_type": "baseline_or_benchmark",
        "goal": "Find citations using the target paper as a baseline or benchmark.",
        "aspects": ["baseline_or_benchmark"],
        "keywords": ["baseline", "benchmark", "基线", "评测"],
        "patterns": ["benchmark baseline"],
        "prompt": "Prioritize evidence where the target paper is used as a baseline or benchmark.",
        "rules": {
            "template_bonus": 20,
            "allowed_evidence_types": [
                "baseline_or_benchmark",
                "performance_comparison",
            ],
            "strict_rules": [
                "requires explicit experimental use as baseline or benchmark",
                "ordinary related work is insufficient",
            ],
            "require_target_marker": True,
            "allow_grouped_citation": False,
        },
    },
    {
        "name": "theoretical_foundation",
        "description": "作为理论基础",
        "template_type": "theoretical_foundation",
        "goal": "Find citations using the target paper as a theoretical foundation.",
        "aspects": ["theoretical_foundation"],
        "keywords": ["theoretical foundation", "理论基础"],
        "patterns": ["foundation follows"],
        "prompt": "Prioritize theoretical foundation evidence.",
        "rules": {
            "template_bonus": 18,
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
    },
    {
        "name": "method_foundation",
        "description": "作为方法来源",
        "template_type": "method_foundation",
        "goal": "Find citations using the target paper as a method foundation.",
        "aspects": ["method_foundation"],
        "keywords": ["method foundation", "method source", "方法来源"],
        "patterns": ["method foundation"],
        "prompt": "Prioritize method foundation evidence.",
        "rules": {
            "template_bonus": 18,
            "allowed_evidence_types": [
                "method_foundation",
                "method_use",
                "method_summary",
            ],
            "strict_rules": [
                "requires target-anchored body text describing or using a concrete target-paper method",
                "plain listing and reference-only evidence are excluded",
                "method summary without adoption or dependency is review-only",
            ],
            "require_target_marker": True,
            "allow_grouped_citation": False,
        },
    },
    {
        "name": "application_extension",
        "description": "应用拓展",
        "template_type": "application_extension",
        "goal": "Find citations extending or applying the target paper.",
        "aspects": ["application_extension"],
        "keywords": ["application", "extension", "应用", "拓展"],
        "patterns": ["extends"],
        "prompt": "Prioritize application extension evidence.",
        "rules": {"template_bonus": 15},
    },
    {
        "name": "important_author_citation",
        "description": "重要作者引用",
        "template_type": "important_author_citation",
        "goal": "Find citations from important authors or fellows.",
        "aspects": ["important_author_citation"],
        "keywords": ["Fellow", "院士", "important author"],
        "patterns": ["fellow"],
        "prompt": "Prioritize positive citations from important authors or Fellows.",
        "rules": {"template_bonus": 15},
    },
    {
        "name": "survey_highlight",
        "description": "综述重点评价",
        "template_type": "survey_highlight",
        "goal": "Find survey papers that highlight the target paper.",
        "aspects": ["survey_highlight"],
        "keywords": ["survey", "review", "综述"],
        "patterns": ["survey highlights"],
        "prompt": "Prioritize survey highlight evidence.",
        "rules": {"template_bonus": 15},
    },
    {
        "name": "long_context_citation",
        "description": "长上下文引用",
        "template_type": "long_context_citation",
        "goal": "Find long-context citations with substantive discussion.",
        "aspects": ["long_context_citation"],
        "keywords": ["long context", "substantial discussion", "长上下文"],
        "patterns": ["substantial discussion"],
        "prompt": "Prioritize long-context citation evidence.",
        "rules": {"template_bonus": 12},
    },
    {
        "name": "positive_evaluation",
        "description": "正向评价",
        "template_type": "positive_evaluation",
        "goal": POSITIVE_EVALUATION_GOAL,
        "aspects": ["positive_evaluation"],
        "keywords": ["positive", "improves", "strong", "正向", "评价"],
        "patterns": ["positive evaluation"],
        "prompt": POSITIVE_EVALUATION_PROMPT,
        "rules": {
            "template_bonus": 12,
            "allowed_evidence_types": [
                "positive_evaluation",
                "capability_recognition",
                "capability_summary",
                "method_summary",
                "rfid_loudspeaker_vibration",
                "through_wall_eavesdropping",
            ],
            "strict_rules": POSITIVE_EVALUATION_ADVISORY_RULES,
            "require_target_marker": True,
            "allow_grouped_citation": False,
        },
    },
    {
        "name": "limitation_or_negative",
        "description": "负面/局限评价",
        "template_type": "limitation_or_negative",
        "goal": "Find limitation or negative evaluation evidence.",
        "aspects": ["limitation_or_negative"],
        "keywords": ["limitation", "negative", "局限", "不足"],
        "patterns": ["limitation"],
        "prompt": "Prioritize limitation or negative evaluation evidence with original citation_text.",
        "rules": {
            "template_bonus": 12,
            "allowed_evidence_types": [
                "limitation_feedback",
                "limitation_or_negative",
            ],
            "strict_rules": [
                "requires an explicit target-anchored limitation, drawback, failure condition, or practical constraint",
                "ordinary related work and neutral capability descriptions are excluded",
            ],
            "require_target_marker": True,
            "allow_grouped_citation": False,
        },
    },
]


class TemplateService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = TemplateRepository(db)

    def list_builtin_templates(self) -> List[AnalysisTemplate]:
        self._ensure_builtin_templates()
        return self.repository.list_builtin_templates()

    def get_template(self, template_id: int) -> AnalysisTemplate:
        template = self.repository.get_template(template_id)
        if template is None:
            raise ValueError(f"AnalysisTemplate {template_id} was not found")
        return template

    def enable_template(self, *, session_id: int, template_id: int) -> AnalysisTemplate:
        source = self.repository.get_template(template_id)
        if source is None:
            raise ValueError(f"AnalysisTemplate {template_id} was not found")
        existing = self.repository.find_session_template(
            session_id=session_id,
            name=source.name,
            template_type=source.template_type,
        )
        if existing is None:
            existing = self.repository.create_template(
                **self._clone_values(source, session_id=session_id, is_active=True)
            )
        else:
            existing.is_active = True
        self.db.commit()
        self.db.refresh(existing)
        return existing

    def disable_template(self, *, session_id: int, template_id: int) -> None:
        source = self.repository.get_template(template_id)
        if source is None:
            raise ValueError(f"AnalysisTemplate {template_id} was not found")
        target = source
        if source.session_id != session_id:
            target = self.repository.find_session_template(
                session_id=session_id,
                name=source.name,
                template_type=source.template_type,
            )
            if target is None:
                target = self.repository.create_template(
                    **self._clone_values(source, session_id=session_id, is_active=False)
                )
        target.is_active = False
        self.db.commit()

    def create_custom_template(
        self,
        *,
        session_id: int,
        template_name: Optional[str] = None,
        natural_language_goal: str,
        template_type: str = "custom",
        positive_keywords: Optional[Iterable[str]] = None,
        negative_keywords: Optional[Iterable[str]] = None,
        required_patterns: Optional[Iterable[str]] = None,
        allowed_evidence_types: Optional[Iterable[str]] = None,
        strict_rules: Optional[Iterable[str]] = None,
        instruction_text: str = "",
        min_citation_chars: int = 0,
        min_citation_words: int = 0,
        require_target_marker: bool = False,
        allow_grouped_citation: bool = False,
        auto_include_in_report: bool = False,
    ) -> AnalysisTemplate:
        keywords = list(positive_keywords or [])
        negative_terms = list(negative_keywords or [])
        patterns = list(required_patterns or [])
        allowed_types = list(allowed_evidence_types or [])
        rules = list(strict_rules or [])
        scoring_rules = {
            "template_origin": "user_defined",
            "template_bonus": 15,
            "min_citation_chars": int(min_citation_chars or 0),
            "min_citation_words": int(min_citation_words or 0),
            "require_target_marker": bool(require_target_marker),
            "allow_grouped_citation": bool(allow_grouped_citation),
            "auto_include_in_report": bool(auto_include_in_report),
            "allowed_evidence_types": allowed_types,
            "strict_rules": rules,
        }
        existing_count = len(
            [
                template
                for template in self.repository.get_active_templates(session_id)
                if not template.is_builtin
            ]
        )
        display_name = (template_name or natural_language_goal or "用户自定义模板").strip()
        template = self.repository.create_template(
            session_kind="scholar_analysis",
            session_id=session_id,
            name=f"custom_{template_type}_{session_id}_{existing_count + 1}",
            description=display_name[:255],
            template_type=template_type or "custom",
            natural_language_goal=natural_language_goal,
            target_aspects_json=json.dumps(
                allowed_types or ([template_type] if template_type else ["custom"]),
                ensure_ascii=False,
            ),
            positive_keywords_json=json.dumps(keywords, ensure_ascii=False),
            negative_keywords_json=json.dumps(negative_terms, ensure_ascii=False),
            required_evidence_patterns_json=json.dumps(patterns, ensure_ascii=False),
            prompt_fragment=(instruction_text or build_custom_prompt_fragment(
                natural_language_goal=natural_language_goal,
                template_type=template_type or "custom",
                positive_keywords=keywords,
            )).strip(),
            scoring_rules_json=json.dumps(scoring_rules, ensure_ascii=False),
            is_builtin=False,
            is_active=True,
        )
        self.db.commit()
        self.db.refresh(template)
        return template

    def update_template(self, template_id: int, **values) -> AnalysisTemplate:
        template = self.repository.get_template(template_id)
        if template is None:
            raise ValueError(f"AnalysisTemplate {template_id} was not found")
        for key, value in values.items():
            if hasattr(template, key):
                setattr(template, key, value)
        self.db.commit()
        self.db.refresh(template)
        return template

    def get_active_templates(self, session_id: int) -> List[AnalysisTemplate]:
        self._ensure_builtin_templates()
        return self.repository.get_active_templates(session_id)

    def preview_matches_for_text(self, session_id: int, text: str) -> List[dict]:
        matches = []
        for template in self.get_active_templates(session_id):
            terms, reason, score = match_template_terms(template, text)
            if terms:
                matches.append(
                    {
                        "template": template,
                        "matched_terms": terms,
                        "matched_reason": reason,
                        "match_score": score,
                    }
                )
        return matches

    def active_template_prompt_snapshot(self, session_id: int) -> str:
        return format_template_snapshots_for_prompt(self.get_active_templates(session_id))

    def active_template_snapshots(self, session_id: int) -> List[dict]:
        return [template_snapshot(template) for template in self.get_active_templates(session_id)]

    def evaluate_finding_templates(
        self,
        *,
        session_id: int,
        finding_payload: dict,
        citation_text: str,
        evidence_context: str = "",
        target_reference_marker: str = "",
        cited_paper_title: str = "",
    ) -> dict:
        return evaluate_templates_for_finding(
            self.get_active_templates(session_id),
            finding_payload,
            citation_text=citation_text,
            evidence_context=evidence_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=cited_paper_title,
        )

    def reapply_templates_to_session(self, session_id: int) -> dict:
        evidences = (
            self.db.query(StrongEvidence)
            .filter(StrongEvidence.scholar_session_id == session_id)
            .all()
        )
        updated = 0
        satisfied = 0
        for evidence in evidences:
            item = self.db.get(DeepAnalysisQueueItem, evidence.queue_item_id) if evidence.queue_item_id else None
            result = self.db.get(FulltextAnalysisResult, evidence.fulltext_result_id)
            if item is None:
                continue
            target_marker = ""
            evidence_context = evidence.citation_text or ""
            if result and result.candidate_spans_json:
                try:
                    diagnostics = json.loads(result.candidate_spans_json)
                except json.JSONDecodeError:
                    diagnostics = {}
                target_marker = str(diagnostics.get("target_reference_marker") or "")
                for preview in diagnostics.get("target_contexts_preview", []) or []:
                    context_text = str(
                        preview.get("context_text")
                        or preview.get("context_text_preview")
                        or ""
                    )
                    if evidence.citation_text and evidence.citation_text in context_text:
                        evidence_context = context_text
                        break
            template_result = self.evaluate_finding_templates(
                session_id=session_id,
                finding_payload={
                    "evidence_type": evidence.aspect,
                    "stance": evidence.stance,
                    "mention_type": evidence.mention_type,
                    "citation_text": evidence.citation_text,
                    "reasoning": evidence.evidence_reason,
                    "keywords": _safe_json_list(evidence.highlight_keywords_json),
                    "keep": True,
                },
                citation_text=evidence.citation_text or "",
                evidence_context=evidence_context,
                target_reference_marker=target_marker,
                cited_paper_title=item.cited_paper_title,
            )
            evidence.matched_template_ids_json = json.dumps(
                template_result.get("matched_template_ids", []),
                ensure_ascii=False,
            )
            evidence.template_match_reason = template_result.get("template_match_reason", "")
            evidence.template_satisfied = bool(template_result.get("template_satisfied", False))
            evidence.template_failure_reason = template_result.get("template_failure_reason", "")
            self.record_template_result_for_evidence(evidence.id, template_result)
            updated += 1
            if evidence.template_satisfied:
                satisfied += 1
        for card in self.db.query(HighlightCard).filter_by(scholar_session_id=session_id).all():
            evidence = self.db.get(StrongEvidence, card.strong_evidence_id) if card.strong_evidence_id else None
            if evidence is None:
                continue
            ids = _safe_json_list(evidence.matched_template_ids_json)
            names = []
            for template_id in ids:
                try:
                    template = self.db.get(AnalysisTemplate, int(template_id))
                except (TypeError, ValueError):
                    template = None
                if template is not None:
                    names.append(template.description or template.name)
            card.matched_template_ids_json = json.dumps(ids, ensure_ascii=False)
            card.matched_template_names = json.dumps(names, ensure_ascii=False)
            card.template_match_reason = evidence.template_match_reason or ""
            card.template_satisfied = evidence.template_satisfied
            card.template_failure_reason = evidence.template_failure_reason or ""
        self.db.commit()
        return {
            "updated_evidence_count": updated,
            "template_satisfied_count": satisfied,
            "template_unsatisfied_count": max(0, updated - satisfied),
        }

    def match_templates_for_queue_item(self, queue_item_id: int) -> List[TemplateMatch]:
        item = self.db.get(DeepAnalysisQueueItem, queue_item_id)
        if item is None:
            raise ValueError(f"DeepAnalysisQueueItem {queue_item_id} was not found")
        self.repository.delete_queue_matches(queue_item_id)
        text = " ".join(
            [
                item.citing_paper_title or "",
                item.cited_paper_title or "",
                item.venue or "",
                item.citing_authors_json or "",
            ]
        )
        matches = self._create_matches(
            session_id=item.scholar_session_id,
            text=text,
            queue_item_id=item.id,
        )
        self.db.commit()
        for match in matches:
            self.db.refresh(match)
        return matches

    def match_templates_for_evidence(self, evidence_id: int) -> List[TemplateMatch]:
        evidence = self.db.get(StrongEvidence, evidence_id)
        if evidence is None:
            raise ValueError(f"StrongEvidence {evidence_id} was not found")
        self.repository.delete_evidence_matches(evidence_id)
        text = " ".join(
            [
                evidence.citation_text or "",
                evidence.aspect or "",
                evidence.stance or "",
                evidence.evidence_reason or "",
            ]
        )
        matches = self._create_matches(
            session_id=evidence.scholar_session_id,
            text=text,
            strong_evidence_id=evidence.id,
        )
        self.db.commit()
        for match in matches:
            self.db.refresh(match)
        return matches

    def list_matches_for_evidence(self, evidence_id: int) -> List[TemplateMatch]:
        return self.repository.list_matches_for_evidence(evidence_id)

    def record_template_result_for_evidence(
        self,
        evidence_id: int,
        template_result: dict,
    ) -> List[TemplateMatch]:
        evidence = self.db.get(StrongEvidence, evidence_id)
        if evidence is None:
            raise ValueError(f"StrongEvidence {evidence_id} was not found")
        self.repository.delete_evidence_matches(evidence_id)
        matches = []
        for evaluation in template_result.get("template_evaluations", []) or []:
            if not evaluation.get("template_satisfied"):
                continue
            matches.append(
                self.repository.create_match(
                    template_id=int(evaluation["template_id"]),
                    strong_evidence_id=evidence_id,
                    matched_terms_json=json.dumps(
                        evaluation.get("matched_terms", []),
                        ensure_ascii=False,
                    ),
                    matched_reason=evaluation.get("template_match_reason", ""),
                    match_score=float(evaluation.get("match_score", 0.0) or 0.0),
                )
            )
        self.db.commit()
        for match in matches:
            self.db.refresh(match)
        return matches

    def _create_matches(
        self,
        *,
        session_id: int,
        text: str,
        queue_item_id: Optional[int] = None,
        strong_evidence_id: Optional[int] = None,
    ) -> List[TemplateMatch]:
        matches = []
        for template in self.get_active_templates(session_id):
            terms, reason, score = match_template_terms(template, text)
            if not terms:
                continue
            matches.append(
                self.repository.create_match(
                    template_id=template.id,
                    queue_item_id=queue_item_id,
                    strong_evidence_id=strong_evidence_id,
                    matched_terms_json=json.dumps(terms, ensure_ascii=False),
                    matched_reason=reason,
                    match_score=score,
                )
            )
        return matches

    def _ensure_builtin_templates(self) -> None:
        configured_names = {spec["name"] for spec in BUILTIN_TEMPLATES}
        active_builtins = self.repository.list_builtin_templates()
        retired_keys = {
            (template.name, template.template_type)
            for template in active_builtins
            if template.name not in configured_names
        }
        for template in active_builtins:
            if (template.name, template.template_type) in retired_keys:
                template.is_active = False
        if retired_keys:
            for template in self.db.query(AnalysisTemplate).filter(
                AnalysisTemplate.is_builtin.is_(False),
                AnalysisTemplate.session_id.is_not(None),
            ):
                if (template.name, template.template_type) in retired_keys:
                    template.is_active = False
        existing_names = {
            template.name
            for template in active_builtins
            if template.name in configured_names
        }
        for spec in BUILTIN_TEMPLATES:
            if spec["name"] in existing_names:
                continue
            self.repository.create_template(
                session_kind="scholar_analysis",
                session_id=None,
                name=spec["name"],
                description=spec["description"],
                template_type=spec["template_type"],
                natural_language_goal=spec["goal"],
                target_aspects_json=json.dumps(spec["aspects"], ensure_ascii=False),
                positive_keywords_json=json.dumps(spec["keywords"], ensure_ascii=False),
                negative_keywords_json="[]",
                required_evidence_patterns_json=json.dumps(spec["patterns"], ensure_ascii=False),
                prompt_fragment=spec["prompt"],
                scoring_rules_json=json.dumps(spec["rules"]),
                is_builtin=True,
                is_active=True,
            )
        self._upgrade_positive_evaluation_defaults()
        self.db.commit()

    def _upgrade_positive_evaluation_defaults(self) -> None:
        """Refresh untouched built-in clones without overwriting user edits."""
        templates = self.db.query(AnalysisTemplate).filter(
            AnalysisTemplate.name == "positive_evaluation",
            AnalysisTemplate.template_type == "positive_evaluation",
        )
        for template in templates:
            if template.natural_language_goal == POSITIVE_EVALUATION_LEGACY_GOAL:
                template.natural_language_goal = POSITIVE_EVALUATION_GOAL
            if template.prompt_fragment == POSITIVE_EVALUATION_LEGACY_PROMPT:
                template.prompt_fragment = POSITIVE_EVALUATION_PROMPT
            rules = _safe_json_dict(template.scoring_rules_json)
            if rules.get("strict_rules") == POSITIVE_EVALUATION_LEGACY_STRICT_RULES:
                rules["strict_rules"] = POSITIVE_EVALUATION_ADVISORY_RULES
                template.scoring_rules_json = json.dumps(
                    rules,
                    ensure_ascii=False,
                )

    def _clone_values(
        self,
        source: AnalysisTemplate,
        *,
        session_id: int,
        is_active: bool,
    ) -> dict:
        return {
            "session_kind": source.session_kind,
            "session_id": session_id,
            "name": source.name,
            "description": source.description,
            "template_type": source.template_type,
            "natural_language_goal": source.natural_language_goal,
            "target_aspects_json": source.target_aspects_json,
            "positive_keywords_json": source.positive_keywords_json,
            "negative_keywords_json": source.negative_keywords_json,
            "required_evidence_patterns_json": source.required_evidence_patterns_json,
            "prompt_fragment": source.prompt_fragment,
            "scoring_rules_json": source.scoring_rules_json,
            "is_builtin": False,
            "is_active": is_active,
        }


def get_template_service(db: Session = Depends(get_db)) -> TemplateService:
    return TemplateService(db)


def _safe_json_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _safe_json_dict(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}

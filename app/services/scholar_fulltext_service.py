"""Scholar queue full-text citation analysis service."""

import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.candidate_spans import find_candidate_spans
from app.analysis.citation_anchor import (
    build_target_citation_anchor,
    citation_text_has_target_anchor,
    extract_alias_contexts,
    extract_target_reference_contexts,
    find_target_reference_anchor,
    reference_entries_by_marker,
)
from app.analysis.evidence_highlighting import build_highlight_keywords
from app.analysis.evidence_scoring import apply_contextual_adjustments, score_finding
from app.analysis.prompt_builder import (
    build_citation_analysis_prompt,
    build_fulltext_anchor_direct_prompt,
    build_fulltext_direct_prompt,
    build_fulltext_direct_repair_prompt,
    build_fulltext_template_direct_prompt,
    build_template_direct_adjudication_prompt,
)
from app.analysis.template_direct_postprocess import (
    direct_evidence_failure_reason_codes,
    postprocess_template_direct_payload,
)
from app.analysis.template_matching import (
    format_template_snapshots_for_prompt,
    template_stance_intent,
)
from app.analysis.target_anchor_validation import validate_citation_target_anchor
from app.analysis.llm_parser import parse_llm_json_payload
from app.core.config import PROJECT_ROOT, settings
from app.db.session import get_db
from app.models import DeepAnalysisQueueItem, FulltextAnalysisResult, PdfAsset, Publication, StrongEvidence
from app.models.constants import (
    SCHOLAR_ANALYSIS_SESSION_KIND,
    is_pdf_ready_status,
)
from app.providers.errors import ProviderException, RETRYABLE_ERROR_CODES
from app.providers.llm_provider import get_llm_provider
from app.schemas.provider import ProviderErrorCode
from app.repositories.task_repo import TaskRepository
from app.schemas.llm import CitationAnalysisResponse, LlmCitationAnalysisRequest
from app.services.evidence_service import EvidenceService
from app.services.task_service import TaskService
from app.services.template_direct_persistence_service import (
    TemplateDirectPersistenceService,
)
from app.services.template_service import TemplateService
from app.tasks.handlers.analyze_citation import MIN_STRONG_EVIDENCE_SCORE


GROUPED_REVIEWABLE_TYPES = {
    "limitation_or_negative",
    "detailed_comparison",
    "positive_evaluation",
    "representative_work",
    "method_foundation",
    "baseline_or_benchmark",
    "application_extension",
    "theoretical_foundation",
    "first_or_seminal_claim",
}


class ScholarFulltextService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.evidence_service = EvidenceService(db)

    def analyze_queue_items(
        self,
        *,
        session_id: int,
        queue_item_ids: Optional[List[int]],
        analysis_scope: str,
        task_id: Optional[int] = None,
        progress_callback: Optional[
            Callable[
                [int, int, Optional[DeepAnalysisQueueItem], str],
                None,
            ]
        ] = None,
    ) -> Dict[str, object]:
        analysis_scope = self._normalize_analysis_scope(analysis_scope)
        initial_result_count = self._count_fulltext_results(session_id)
        all_session_items = self._list_target_items(session_id, None)
        items = self._list_target_items(session_id, queue_item_ids)
        summary: Dict[str, object] = {
            "total": len(items),
            "total_queue_items": len(all_session_items),
            "selected_items": sum(
                1 for item in all_session_items if item.queue_status == "selected"
            ),
            "ready_items": sum(
                1
                for item in all_session_items
                if item.queue_status == "selected"
                and is_pdf_ready_status(item.pdf_readiness_status)
            ),
            "succeeded": 0,
            "skipped": 0,
            "failed": 0,
            "analyzed_count": 0,
            "skipped_need_pdf_count": 0,
            "skipped_not_selected_count": 0,
            "failed_item_count": 0,
            "fulltext_result_count": 0,
            "current_run_result_count": 0,
            "current_run_succeeded_count": 0,
            "current_run_failed_count": 0,
            "session_fulltext_result_count": initial_result_count,
            "strong_evidence_count": 0,
            "generated_strong_evidence_count": 0,
            "persisted_strong_evidence_count": 0,
            "generated_highlight_card_count": 0,
            "persisted_highlight_card_count": 0,
            "strong_evidence_persistence_failed_count": 0,
            "highlight_card_persistence_failed_count": 0,
            "filtered_findings_count": 0,
            "filter_reason_distribution": {},
            "analysis_scope": analysis_scope,
            "fulltext_chars": 0,
            "llm_findings_count": 0,
            "parsed_evidence_count": 0,
            "include_evidence_count": 0,
            "review_evidence_count": 0,
            "exclude_evidence_count": 0,
            "extracted_candidate_count": 0,
            "aligned_candidate_count": 0,
            "unresolved_candidate_count": 0,
            "template_eligible_candidate_count": 0,
            "template_matched_candidate_count": 0,
            "verified_evidence_count": 0,
            "verified_substantive_evidence_count": 0,
            "ordinary_reference_false_positive_count": 0,
            "reference_mismatch_false_positive_count": 0,
            "final_include_count": 0,
            "final_review_count": 0,
            "final_exclude_count": 0,
            "warnings": [],
        }
        if progress_callback is not None:
            progress_callback(0, len(items), None, "preparing")
        for index, item in enumerate(items, start=1):
            if progress_callback is not None:
                progress_callback(index - 1, len(items), item, "started")
            if item.queue_status != "selected":
                summary["skipped"] += 1
                summary["skipped_not_selected_count"] += 1
                summary["warnings"].append(f"queue_item:{item.id}:not_selected")
                if progress_callback is not None:
                    progress_callback(
                        index,
                        len(items),
                        item,
                        "skipped_not_selected",
                    )
                continue
            blocking_reason = self._pdf_blocking_reason(item)
            if blocking_reason == "unsupported_pdf_status":
                summary["skipped"] += 1
                summary["skipped_need_pdf_count"] += 1
                summary["warnings"].append(
                    f"queue_item:{item.id}:unsupported_pdf_status:{item.pdf_readiness_status}"
                )
                if progress_callback is not None:
                    progress_callback(
                        index,
                        len(items),
                        item,
                        "skipped_need_pdf",
                    )
                continue
            if blocking_reason in {"invalid_pdf_binding", "pdf_extract_not_ready"}:
                summary["skipped"] += 1
                summary["skipped_need_pdf_count"] += 1
                summary["warnings"].append(f"queue_item:{item.id}:{blocking_reason}")
                if progress_callback is not None:
                    progress_callback(index, len(items), item, blocking_reason)
                continue
            if blocking_reason == "missing_extracted_text":
                summary["failed"] += 1
                summary["failed_item_count"] += 1
                summary["warnings"].append(f"queue_item:{item.id}:missing_extracted_text")
                if progress_callback is not None:
                    progress_callback(
                        index,
                        len(items),
                        item,
                        "missing_extracted_text",
                    )
                continue

            try:
                analysis_result = self.analyze_single_queue_item(
                    queue_item_id=item.id,
                    analysis_scope=analysis_scope,
                    task_id=task_id,
                )
            except Exception as exc:
                self.db.rollback()
                summary["failed"] += 1
                summary["failed_item_count"] += 1
                summary["warnings"].append(f"queue_item:{item.id}:{exc}")
                if progress_callback is not None:
                    progress_callback(index, len(items), item, "failed")
            else:
                summary["succeeded"] += 1
                summary["analyzed_count"] += 1
                if analysis_scope == "fulltext_template_direct":
                    direct_counts = self._direct_evidence_counts(
                        self._load_json(analysis_result.parsed_result_json)
                    )
                    for key, value in direct_counts.items():
                        summary[key] = int(summary.get(key) or 0) + value
                    persistence_counts = self._direct_persistence_counts(
                        analysis_result
                    )
                    for key, value in persistence_counts.items():
                        summary[key] = int(summary.get(key) or 0) + int(value)
                    candidate_payload = self._load_json(
                        analysis_result.candidate_spans_json
                    )
                    summary["warnings"].extend(
                        str(warning)
                        for warning in candidate_payload.get("warnings", [])
                        if warning
                    )
                    summary["llm_findings_count"] = summary["parsed_evidence_count"]
                    parsed_payload = self._load_json(
                        analysis_result.parsed_result_json
                    )
                    run_evidences = parsed_payload.get("evidences", [])
                    summary["filtered_findings_count"] += sum(
                        1
                        for evidence in run_evidences
                        if isinstance(evidence, dict)
                        and evidence.get("recommendation") != "include"
                    )
                    self._merge_reason_counts(
                        summary["filter_reason_distribution"],
                        self._direct_filter_reason_distribution(run_evidences),
                    )
                if progress_callback is not None:
                    progress_callback(index, len(items), item, "succeeded")

        final_result_count = self._count_fulltext_results(session_id)
        summary["current_run_result_count"] = max(
            0,
            final_result_count - initial_result_count,
        )
        summary["current_run_succeeded_count"] = int(summary["succeeded"])
        summary["current_run_failed_count"] = int(summary["failed"])
        summary["session_fulltext_result_count"] = final_result_count
        # Kept for compatibility; its semantics are now explicitly run-scoped.
        summary["fulltext_result_count"] = summary["current_run_result_count"]
        if analysis_scope != "fulltext_template_direct":
            summary["strong_evidence_count"] = self._count_strong_evidence(session_id)
        diagnostics = self.list_analysis_diagnostics(session_id)
        if diagnostics:
            latest = diagnostics[0]
            summary["fulltext_chars"] = latest.get("fulltext_chars") or 0
            if analysis_scope != "fulltext_template_direct":
                summary["llm_findings_count"] = latest.get("llm_findings_count") or 0
        return summary

    def analyze_single_queue_item(
        self,
        *,
        queue_item_id: int,
        analysis_scope: str,
        task_id: Optional[int] = None,
    ) -> FulltextAnalysisResult:
        analysis_scope = self._normalize_analysis_scope(analysis_scope)
        item = self.db.get(DeepAnalysisQueueItem, queue_item_id)
        if item is None:
            raise ValueError(f"DeepAnalysisQueueItem {queue_item_id} was not found")
        if item.queue_status != "selected":
            raise ValueError("Queue item must be selected before analysis")
        blocking_reason = self._pdf_blocking_reason(item)
        if blocking_reason:
            raise ValueError(blocking_reason)

        pdf_asset = self.db.get(PdfAsset, item.pdf_asset_id) if item.pdf_asset_id else None
        if pdf_asset is None:
            raise ValueError("invalid_pdf_binding")
        if pdf_asset.extract_status != "succeeded":
            raise ValueError("pdf_extract_not_ready")
        if not pdf_asset.extracted_text_path:
            raise ValueError("missing_extracted_text")

        extracted_path = Path(pdf_asset.extracted_text_path)
        if not extracted_path.exists():
            raise ValueError("missing_extracted_text")

        extracted_text = extracted_path.read_text(encoding="utf-8")
        if analysis_scope in {"fulltext_direct", "fulltext_anchor_direct", "fulltext_template_direct"} and not extracted_text.strip():
            raise ValueError("empty_extracted_text")
        anchor = build_target_citation_anchor(item.cited_paper_title)
        template_service = TemplateService(self.db)
        active_templates = template_service.get_active_templates(item.scholar_session_id)
        template_snapshot_json = template_service.active_template_prompt_snapshot(
            item.scholar_session_id
        )
        template_fragments = [template_snapshot_json] if active_templates else []
        candidate_spans = []
        request = None
        cited_publication = self.db.get(Publication, item.cited_publication_id)
        cited_authors = self._load_authors(cited_publication)
        reference_anchor = None
        target_reference_contexts = []
        target_alias_contexts = []
        compact_fallback = False
        original_fulltext_chars = len(extracted_text)
        if analysis_scope in {"fulltext_direct", "fulltext_anchor_direct", "fulltext_template_direct"}:
            if len(extracted_text) > settings.fulltext_direct_max_chars and analysis_scope != "fulltext_template_direct":
                raise ValueError("fulltext_too_long_for_direct_analysis")
            reference_anchor = find_target_reference_anchor(
                extracted_text,
                item.cited_paper_title,
                cited_doi=cited_publication.doi if cited_publication else None,
                cited_authors=cited_authors,
            )
            if analysis_scope == "fulltext_template_direct":
                if reference_anchor is not None:
                    target_reference_contexts = extract_target_reference_contexts(
                        extracted_text,
                        reference_anchor.reference_marker,
                        max_contexts=50,
                    )
                prompt_full_text = extracted_text
                if len(extracted_text) > settings.fulltext_direct_max_chars:
                    compact_fallback = True
                    prompt_full_text = self._build_template_direct_compact_text(
                        full_text=extracted_text,
                        reference_anchor=reference_anchor,
                        target_reference_contexts=target_reference_contexts,
                    )
                prompt_text = build_fulltext_template_direct_prompt(
                    citing_paper_title=item.citing_paper_title,
                    cited_paper_title=item.cited_paper_title,
                    cited_paper_year=cited_publication.year if cited_publication else None,
                    cited_paper_venue=cited_publication.venue if cited_publication else None,
                    cited_paper_doi=cited_publication.doi if cited_publication else None,
                    cited_paper_authors=cited_authors,
                    target_reference_marker=(
                        reference_anchor.reference_marker_text
                        if reference_anchor
                        else None
                    ),
                    target_reference_entry=(
                        reference_anchor.reference_entry_text
                        if reference_anchor
                        else None
                    ),
                    target_reference_contexts=target_reference_contexts,
                    full_text=prompt_full_text,
                    template_prompt_fragments=template_fragments,
                )
            elif analysis_scope == "fulltext_anchor_direct":
                if reference_anchor is not None:
                    target_reference_contexts = extract_target_reference_contexts(
                        extracted_text,
                        reference_anchor.reference_marker,
                    )
                target_alias_contexts = extract_alias_contexts(
                    extracted_text,
                    self._target_aliases(item.cited_paper_title, cited_authors),
                )
                prompt_text = build_fulltext_anchor_direct_prompt(
                    citing_paper_title=item.citing_paper_title,
                    cited_paper_title=item.cited_paper_title,
                    cited_paper_year=cited_publication.year if cited_publication else None,
                    cited_paper_venue=cited_publication.venue if cited_publication else None,
                    cited_paper_doi=cited_publication.doi if cited_publication else None,
                    cited_paper_authors=cited_authors,
                    target_reference_marker=reference_anchor.reference_marker_text if reference_anchor else None,
                    target_reference_entry=reference_anchor.reference_entry_text if reference_anchor else None,
                    target_reference_contexts=target_reference_contexts,
                    target_alias_contexts=target_alias_contexts,
                    full_text=extracted_text,
                    template_prompt_fragments=template_fragments,
                )
            else:
                prompt_text = build_fulltext_direct_prompt(
                    citing_paper_title=item.citing_paper_title,
                    cited_paper_title=item.cited_paper_title,
                    cited_paper_year=cited_publication.year if cited_publication else None,
                    cited_paper_venue=cited_publication.venue if cited_publication else None,
                    cited_paper_doi=cited_publication.doi if cited_publication else None,
                    cited_paper_authors=cited_authors,
                    target_reference_marker=reference_anchor.reference_marker_text if reference_anchor else None,
                    target_reference_entry=reference_anchor.reference_entry_text if reference_anchor else None,
                    full_text=extracted_text,
                    template_prompt_fragments=template_fragments,
                )
            request = LlmCitationAnalysisRequest(
                target_title=anchor.title,
                analysis_scope=analysis_scope,
                citing_paper_title=item.citing_paper_title,
                cited_paper_title=item.cited_paper_title,
                cited_paper_year=cited_publication.year if cited_publication else None,
                cited_paper_venue=cited_publication.venue if cited_publication else None,
                cited_paper_doi=cited_publication.doi if cited_publication else None,
                cited_paper_authors=cited_authors,
                full_text=extracted_text,
                template_prompt_fragments=template_fragments,
                prompt_text=prompt_text,
            )
            if analysis_scope == "fulltext_template_direct":
                return self._run_fulltext_template_direct(
                    item=item,
                    provider=get_llm_provider(),
                    request=request,
                    extracted_text=extracted_text,
                    active_templates=active_templates,
                    template_snapshot_json=template_snapshot_json,
                    reference_anchor=reference_anchor,
                    reference_entries_by_marker=reference_entries_by_marker(extracted_text),
                    compact_fallback=compact_fallback,
                    original_fulltext_chars=original_fulltext_chars,
                    target_reference_context_count=len(
                        target_reference_contexts
                    ),
                    task_id=task_id,
                )
        else:
            candidate_spans = find_candidate_spans(extracted_text, anchor)
            prompt_text = build_citation_analysis_prompt(
                anchor=anchor,
                candidate_spans=candidate_spans,
                template_prompt_fragments=template_fragments,
            )
            request = LlmCitationAnalysisRequest(
                target_title=anchor.title,
                analysis_scope="candidate_spans",
                candidate_spans=[span.text for span in candidate_spans],
                template_prompt_fragments=template_fragments,
                prompt_text=prompt_text,
            )

        provider = get_llm_provider()
        debug_raw_response_text = ""
        try:
            parsed_result = provider.analyze_citation(request)
        except ProviderException as exc:
            debug_raw_response_text = str(exc.raw_output_preview or "")
            if analysis_scope in {"fulltext_direct", "fulltext_anchor_direct"} and exc.code == ProviderErrorCode.PROVIDER_SCHEMA_ERROR:
                repaired_result = self._repair_fulltext_direct_with_provider(
                    provider=provider,
                    request=request,
                    raw_output=exc.raw_output_preview,
                    cited_paper_title=item.cited_paper_title,
                )
                if repaired_result is None:
                    repaired_result = self._repair_fulltext_direct_response(
                        raw_output=exc.raw_output_preview,
                        full_text=extracted_text,
                        cited_paper_title=item.cited_paper_title,
                    )
                if repaired_result is None:
                    self._persist_failed_fulltext_result(
                        item=item,
                        provider=provider,
                        analysis_scope=analysis_scope,
                        fulltext_chars=len(extracted_text),
                        error_message=str(exc),
                        diagnostic_payload={
                            "error": "provider_schema_error",
                            "raw_output_preview": exc.raw_output_preview,
                            "parse_error": exc.parse_error,
                            "schema_error": exc.schema_error,
                        },
                        prompt_text=request.prompt_text if request else "",
                        task_id=task_id,
                    )
                    raise
                parsed_result = repaired_result
            else:
                raise

        fulltext_result = FulltextAnalysisResult(
            scholar_session_id=item.scholar_session_id,
            queue_item_id=item.id,
            citation_edge_id=item.citation_edge_id,
            analysis_scope=analysis_scope,
            status="succeeded",
            llm_provider=getattr(provider, "provider_name", settings.llm_provider),
            llm_model=settings.llm_model,
            prompt_version="phase13.v1",
            candidate_spans_json="{}",
            parsed_result_json=parsed_result.model_dump_json(),
        )
        self.db.add(fulltext_result)
        self.db.flush()

        normalized_result_payload = self._result_payload(parsed_result)
        normalized_findings = normalized_result_payload.get("findings", [])
        finding_diagnostics = []
        for finding_index, finding in enumerate(parsed_result.findings):
            finding_diagnostics.append(
                self._evaluate_finding(
                    finding_index=finding_index,
                    finding=finding,
                    item=item,
                    fulltext_result=fulltext_result,
                    candidate_spans=candidate_spans,
                    extracted_text=extracted_text,
                    analysis_scope=analysis_scope,
                    reference_anchor=reference_anchor,
                    target_reference_contexts=target_reference_contexts,
                )
            )
        normalized_findings = self._merge_template_diagnostics_into_findings(
            normalized_findings,
            finding_diagnostics,
        )

        raw_response_text = debug_raw_response_text or self._provider_raw_response(provider, parsed_result)
        candidate_spans_payload = self._build_result_diagnostics_payload(
            analysis_scope=analysis_scope,
            extracted_text=extracted_text,
            candidate_spans=candidate_spans,
            finding_diagnostics=finding_diagnostics,
            normalized_findings=normalized_findings,
            prompt_text=request.prompt_text if request else "",
            raw_response_text=raw_response_text,
            fulltext_result=fulltext_result,
            task_id=task_id,
            provider=provider,
            reference_anchor=reference_anchor,
            target_reference_contexts=target_reference_contexts,
            target_alias_contexts=target_alias_contexts,
            active_templates=active_templates,
            template_snapshot_json=template_snapshot_json,
        )
        fulltext_result.candidate_spans_json = json.dumps(
            candidate_spans_payload,
            ensure_ascii=False,
        )
        fulltext_result.parsed_result_json = json.dumps(
            {
                "findings": normalized_findings,
                "diagnostics": {
                    "llm_findings_count": len(parsed_result.findings),
                    "generated_strong_evidence_count": sum(
                        1
                        for finding_diagnostic in finding_diagnostics
                        if finding_diagnostic.get("generated_strong_evidence")
                    ),
                    "filtered_findings_count": sum(
                        1
                        for finding_diagnostic in finding_diagnostics
                        if not finding_diagnostic.get("generated_strong_evidence")
                    ),
                },
            },
            ensure_ascii=False,
        )

        item.queue_status = "analyzed"
        self.db.commit()
        self.db.refresh(fulltext_result)
        return fulltext_result

    def _evaluate_finding(
        self,
        *,
        finding_index: int,
        finding,
        item: DeepAnalysisQueueItem,
        fulltext_result: FulltextAnalysisResult,
        candidate_spans: List,
        extracted_text: str,
        analysis_scope: str,
        reference_anchor,
        target_reference_contexts,
    ) -> Dict[str, object]:
        citation_text = (self._finding_attr(finding, "citation_text", "") or "").strip()
        evidence_type = self._finding_attr(finding, "evidence_type", "")
        stance = self._finding_attr(finding, "stance", "")
        mention_type = self._finding_attr(finding, "mention_type", "")
        keep = self._finding_attr(finding, "keep", True)
        reasoning = self._finding_attr(finding, "reasoning", "")
        finding_snapshot = self._finding_snapshot(finding)
        target_reference_marker = (
            reference_anchor.reference_marker_text if reference_anchor else ""
        )
        contains_target_marker = citation_text_has_target_anchor(
            citation_text,
            reference_anchor.reference_marker if reference_anchor else None,
        )
        anchor_validation = validate_citation_target_anchor(
            citation_text=citation_text,
            target_reference_marker=reference_anchor.reference_marker if reference_anchor else None,
            cited_paper_title=item.cited_paper_title,
            cited_authors_json=item.cited_authors_json,
            reference_entry_text=reference_anchor.reference_entry_text if reference_anchor else "",
        )
        if (
            anchor_validation.anchor_validation_reason == "target_anchor_missing"
            and citation_text
        ):
            expanded_citation_text = self._expand_to_target_anchor_sentence(
                citation_text=citation_text,
                full_text=extracted_text,
                reference_anchor=reference_anchor,
            )
            if expanded_citation_text and expanded_citation_text != citation_text:
                citation_text = expanded_citation_text
                finding = self._override_finding_citation_text(finding, citation_text)
                contains_target_marker = citation_text_has_target_anchor(
                    citation_text,
                    reference_anchor.reference_marker if reference_anchor else None,
                )
                anchor_validation = validate_citation_target_anchor(
                    citation_text=citation_text,
                    target_reference_marker=(
                        reference_anchor.reference_marker if reference_anchor else None
                    ),
                    cited_paper_title=item.cited_paper_title,
                    cited_authors_json=item.cited_authors_json,
                    reference_entry_text=(
                        reference_anchor.reference_entry_text if reference_anchor else ""
                    ),
                )
        in_target_reference_context = any(
            citation_text and citation_text in context.context_text
            for context in (target_reference_contexts or [])
        )
        template_context = self._template_context_for_finding(
            citation_text=citation_text,
            target_reference_contexts=target_reference_contexts,
        )
        template_result = TemplateService(self.db).evaluate_finding_templates(
            session_id=item.scholar_session_id,
            finding_payload=finding_snapshot,
            citation_text=citation_text,
            evidence_context=template_context,
            target_reference_marker=target_reference_marker,
            cited_paper_title=item.cited_paper_title,
        )
        diagnostic = {
            "finding_index": finding_index,
            "citation_text_preview": self._truncate(citation_text, 240),
            "evidence_type": evidence_type,
            "stance": stance,
            "mention_type": mention_type,
            "keep": keep,
            "target_reference_marker": target_reference_marker,
            "citation_text_contains_target_marker": contains_target_marker,
            "citation_text_contains_other_marker": anchor_validation.citation_text_contains_other_marker,
            "anchor_validation_status": anchor_validation.anchor_validation_status,
            "anchor_validation_reason": anchor_validation.anchor_validation_reason,
            "citation_text_in_target_context": in_target_reference_context,
            "generated_strong_evidence": False,
            "filter_reason": "unknown",
            "promotion_decision": "filtered",
            "evidence_strength_if_saved": None,
            "needs_human_review": False,
            "reasoning": reasoning,
            **template_result,
        }
        if keep is False:
            diagnostic["filter_reason"] = "keep_false"
            return diagnostic
        if not citation_text:
            diagnostic["filter_reason"] = "no_citation_text"
            return diagnostic
        if mention_type == "reference_only":
            diagnostic["filter_reason"] = "reference_only"
            return diagnostic
        if not anchor_validation.is_valid:
            diagnostic["filter_reason"] = anchor_validation.anchor_validation_reason
            diagnostic["promotion_decision"] = "filtered_target_anchor_validation"
            return diagnostic
        if (
            mention_type == "grouped_citation"
            and anchor_validation.anchor_validation_status == "valid_grouped"
            and evidence_type in {"positive_evaluation", "application_extension", "theoretical_foundation"}
            and anchor_validation.anchor_validation_reason != "title_alias_anchor_found"
        ):
            diagnostic["filter_reason"] = "grouped_citation_not_promoted_to_strong_claim"
            diagnostic["promotion_decision"] = "filtered_grouped_anchor_requires_review"
            diagnostic["needs_human_review"] = True
            return diagnostic
        if analysis_scope == "fulltext_direct":
            fulltext_filter_reason = self._fulltext_direct_filter_reason(
                citation_text=citation_text,
                mention_type=mention_type,
                full_text=extracted_text,
                cited_paper_title=item.cited_paper_title,
                evidence_type=evidence_type,
                stance=stance,
                reference_anchor=reference_anchor,
                citation_text_contains_target_marker=contains_target_marker,
                citation_text_in_target_context=(
                    anchor_validation.anchor_validation_reason == "title_alias_anchor_found"
                ),
            )
            if fulltext_filter_reason:
                diagnostic["filter_reason"] = fulltext_filter_reason
                return diagnostic

        is_self_citation = item.self_citation_status == "self_citation"
        score = apply_contextual_adjustments(
            score_finding(finding),
            is_self_citation=is_self_citation,
        )
        if evidence_type == "background" and stance == "neutral":
            upgraded_type = self._background_anchor_upgrade_type(
                citation_text=citation_text,
                reasoning=reasoning,
            )
            if upgraded_type:
                upgraded_finding = self._override_finding_fields(
                    finding,
                    evidence_type=upgraded_type,
                    stance="negative" if upgraded_type == "limitation_or_negative" else "neutral",
                    mention_type=(
                        "comparison"
                        if upgraded_type in {"detailed_comparison", "limitation_or_negative"}
                        else mention_type
                    ),
                )
                evidence = self._save_evidence(
                    finding=upgraded_finding,
                    item=item,
                    fulltext_result=fulltext_result,
                    candidate_spans=candidate_spans,
                    is_self_citation=is_self_citation,
                    score_value=max(score.score, 0.65),
                    evidence_strength="moderate",
                    evidence_reason=(
                        "该证据虽然被模型初判为背景引用，但原文包含目标论文锚点以及"
                        "比较、局限、设计权衡或机制引入等实质性判断线索，需人工复核。"
                    ),
                    anchor_status=self._anchor_status_for_finding(
                        mention_type=mention_type,
                        citation_text=citation_text,
                        reference_anchor=reference_anchor,
                        in_target_reference_context=in_target_reference_context,
                    ),
                    template_result=template_result,
                )
                diagnostic["generated_strong_evidence"] = True
                diagnostic["filter_reason"] = "saved"
                diagnostic["promotion_decision"] = "saved_background_anchor_upgrade"
                diagnostic["evidence_strength_if_saved"] = "moderate"
                diagnostic["needs_human_review"] = True
                diagnostic["evidence_type"] = upgraded_type
                TemplateService(self.db).record_template_result_for_evidence(
                    evidence.id,
                    template_result,
                )
                return diagnostic
            if self._should_save_representative_work(
                evidence_type=evidence_type,
                mention_type=mention_type,
                citation_text=citation_text,
                reasoning=reasoning,
                citation_text_contains_target_marker=contains_target_marker,
            ):
                evidence = self._save_evidence(
                    finding=self._override_finding_type(finding, "representative_work"),
                    item=item,
                    fulltext_result=fulltext_result,
                    candidate_spans=candidate_spans,
                    is_self_citation=is_self_citation,
                    score_value=max(score.score, 0.65),
                    evidence_strength="moderate",
                    evidence_reason=(
                        "该证据属于代表性相关工作/领域定位引用，不是直接正向评价；"
                        "适合人工复核后纳入汇报。"
                    ),
                    anchor_status=self._anchor_status_for_finding(
                        mention_type=mention_type,
                        citation_text=citation_text,
                        reference_anchor=reference_anchor,
                        in_target_reference_context=in_target_reference_context,
                    ),
                    template_result=template_result,
                )
                diagnostic["generated_strong_evidence"] = True
                diagnostic["filter_reason"] = "saved"
                diagnostic["promotion_decision"] = "saved_representative_review"
                diagnostic["evidence_strength_if_saved"] = "moderate"
                diagnostic["needs_human_review"] = True
                diagnostic["evidence_type"] = "representative_work"
                TemplateService(self.db).record_template_result_for_evidence(
                    evidence.id,
                    template_result,
                )
                return diagnostic
            diagnostic["filter_reason"] = "background_neutral"
            return diagnostic

        if self._should_save_grouped_review_finding(finding):
            grouped_score = max(score.score, MIN_STRONG_EVIDENCE_SCORE)
            grouped_strength = "moderate"
            evidence = self._save_evidence(
                finding=finding,
                item=item,
                fulltext_result=fulltext_result,
                candidate_spans=candidate_spans,
                is_self_citation=is_self_citation,
                score_value=grouped_score,
                evidence_strength=grouped_strength,
                evidence_reason=(
                    f"{score.rationale} 这是成组引用证据，可能同时适用于多个被引论文，"
                    "需要人工确认归因范围。"
                ),
                anchor_status=self._anchor_status_for_finding(
                    mention_type=mention_type,
                    citation_text=citation_text,
                    reference_anchor=reference_anchor,
                    in_target_reference_context=in_target_reference_context,
                ),
                template_result=template_result,
            )
            diagnostic["generated_strong_evidence"] = True
            diagnostic["filter_reason"] = "grouped_citation_saved_for_review"
            diagnostic["promotion_decision"] = "saved_review_needed"
            diagnostic["evidence_strength_if_saved"] = grouped_strength
            diagnostic["needs_human_review"] = True
            TemplateService(self.db).record_template_result_for_evidence(
                evidence.id,
                template_result,
            )
            return diagnostic

        if score.score < MIN_STRONG_EVIDENCE_SCORE:
            diagnostic["filter_reason"] = (
                "grouped_citation_too_ambiguous"
                if mention_type == "grouped_citation"
                else "low_strength"
            )
            return diagnostic

        evidence = self._save_evidence(
            finding=finding,
            item=item,
            fulltext_result=fulltext_result,
            candidate_spans=candidate_spans,
            is_self_citation=is_self_citation,
            score_value=score.score,
            evidence_strength=score.evidence_strength,
            evidence_reason=score.rationale,
            anchor_status=self._anchor_status_for_finding(
                mention_type=mention_type,
                citation_text=citation_text,
                reference_anchor=reference_anchor,
                in_target_reference_context=in_target_reference_context,
            ),
            template_result=template_result,
        )
        diagnostic["generated_strong_evidence"] = True
        diagnostic["filter_reason"] = "saved"
        diagnostic["promotion_decision"] = "saved"
        diagnostic["evidence_strength_if_saved"] = score.evidence_strength
        TemplateService(self.db).record_template_result_for_evidence(
            evidence.id,
            template_result,
        )
        return diagnostic

    def _run_fulltext_template_direct(
        self,
        *,
        item: DeepAnalysisQueueItem,
        provider,
        request: LlmCitationAnalysisRequest,
        extracted_text: str,
        active_templates: List,
        template_snapshot_json: str,
        reference_anchor,
        reference_entries_by_marker: Dict[str, str],
        compact_fallback: bool,
        original_fulltext_chars: int,
        target_reference_context_count: int,
        task_id: Optional[int],
    ) -> FulltextAnalysisResult:
        try:
            parsed_result = self._analyze_direct_with_transient_retries(
                provider,
                request,
            )
        except ProviderException as exc:
            final_error = exc
            if exc.code == ProviderErrorCode.PROVIDER_SCHEMA_ERROR:
                retry_request = request.model_copy(
                    update={
                        "prompt_text": (
                            f"{request.prompt_text or ''}\n\n"
                            "RETRY AFTER INVALID OR TRUNCATED JSON:\n"
                            "Return the same analysis as one complete, compact JSON object. "
                            "Keep every distinct evidence item, but keep evidence_quote to the "
                            "exact sentence, evidence_context and surrounding_context to at most "
                            "1200 characters each, and each explanation to at most 300 characters. "
                            "Use only claim_type values listed in the schema. Do not output Markdown."
                        )
                    }
                )
                try:
                    parsed_result = self._analyze_direct_with_transient_retries(
                        provider,
                        retry_request,
                    )
                except ProviderException as retry_exc:
                    final_error = retry_exc
                else:
                    final_error = None
            if final_error is not None:
                self._persist_failed_fulltext_result(
                    item=item,
                    provider=provider,
                    analysis_scope="fulltext_template_direct",
                    fulltext_chars=len(extracted_text),
                    error_message=str(final_error),
                    diagnostic_payload={
                        "error": final_error.code.value,
                        "raw_output_preview": final_error.raw_output_preview,
                        "parse_error": final_error.parse_error,
                        "schema_error": final_error.schema_error,
                        "retry_attempted": (
                            exc.code == ProviderErrorCode.PROVIDER_SCHEMA_ERROR
                            or exc.code in RETRYABLE_ERROR_CODES
                        ),
                        "transient_max_retries": int(
                            settings.llm_transient_max_retries
                        ),
                    },
                    prompt_text=request.prompt_text if request else "",
                    task_id=task_id,
                )
                raise final_error

        result_payload = parsed_result.model_dump()
        cited_publication = self.db.get(Publication, item.cited_publication_id)
        result_payload = postprocess_template_direct_payload(
            result_payload,
            citing_paper_title=item.citing_paper_title,
            cited_paper_title=item.cited_paper_title,
            cited_paper_doi=cited_publication.doi if cited_publication else None,
            target_reference_marker=(
                reference_anchor.reference_marker_text
                if reference_anchor
                else result_payload.get("target_reference_marker", "")
            ),
            target_reference_entry=(
                reference_anchor.reference_entry_text
                if reference_anchor
                else result_payload.get("target_reference_entry", "")
            ),
            reference_entries_by_marker=reference_entries_by_marker,
            cited_paper_authors=self._load_authors(cited_publication),
            cited_paper_year=cited_publication.year if cited_publication else None,
            target_reference_resolved=reference_anchor is not None,
        )
        result_payload = self._adjudicate_direct_evidences(
            item=item,
            provider=provider,
            payload=result_payload,
            active_templates=active_templates,
        )
        result_payload = self._apply_active_templates_to_direct_payload(
            item=item,
            payload=result_payload,
            active_templates=active_templates,
        )
        evidences = result_payload.get("evidences", [])
        evidence_counts = self._direct_evidence_counts(result_payload)
        filter_reason_distribution = self._direct_filter_reason_distribution(
            evidences
        )
        filtered_findings_count = sum(
            1
            for evidence in evidences
            if isinstance(evidence, dict)
            and evidence.get("recommendation") != "include"
        )
        result_payload.setdefault("diagnostics", {}).update(evidence_counts)
        result_payload["diagnostics"]["llm_findings_count"] = evidence_counts[
            "parsed_evidence_count"
        ]
        result_payload["diagnostics"].update(
            {
                "filtered_findings_count": filtered_findings_count,
                "filter_reason_distribution": filter_reason_distribution,
            }
        )
        raw_response_text = self._provider_raw_response(provider, parsed_result)
        candidate_payload = {
            "mode": "fulltext_template_direct",
            "fulltext_chars": len(extracted_text),
            "original_fulltext_chars": original_fulltext_chars,
            "max_chars": settings.fulltext_direct_max_chars,
            "compact_fallback": compact_fallback,
            "original_fulltext_too_long": compact_fallback,
            "active_template_count": len(active_templates),
            "active_template_names": [
                template.description or template.name
                for template in active_templates
            ],
            "prompt_contains_templates": bool(active_templates),
            "prompt_template_snapshot_json": template_snapshot_json,
            "target_reference_marker": (
                reference_anchor.reference_marker_text if reference_anchor else result_payload.get("target_reference_marker", "")
            ),
            "target_reference_entry": (
                reference_anchor.reference_entry_text if reference_anchor else result_payload.get("target_reference_entry", "")
            ),
            "reference_anchor_source": (
                "deterministic_resolver" if reference_anchor else "llm_unresolved_fallback"
            ),
            "reference_anchor_match_method": (
                reference_anchor.match_method if reference_anchor else ""
            ),
            "reference_anchor_match_score": (
                reference_anchor.match_score if reference_anchor else 0.0
            ),
            "template_direct_evidence_count": len(evidences),
            "target_reference_context_count": target_reference_context_count,
            "llm_findings_count": evidence_counts["parsed_evidence_count"],
            **evidence_counts,
            "include_count": evidence_counts["include_evidence_count"],
            "review_count": evidence_counts["review_evidence_count"],
            "exclude_count": evidence_counts["exclude_evidence_count"],
            "filtered_findings_count": filtered_findings_count,
            "filter_reason_distribution": filter_reason_distribution,
            "template_satisfied_count": sum(
                1 for evidence in evidences if evidence.get("template_satisfied") is True
            ),
            "template_unsatisfied_count": sum(
                1 for evidence in evidences if evidence.get("template_satisfied") is False
            ),
            "template_failure_reason_distribution": self._direct_template_failure_distribution(evidences),
            "prompt_chars": len(request.prompt_text or ""),
            "raw_response_chars": len(raw_response_text or ""),
        }
        fulltext_result = FulltextAnalysisResult(
            scholar_session_id=item.scholar_session_id,
            queue_item_id=item.id,
            citation_edge_id=item.citation_edge_id,
            analysis_scope="fulltext_template_direct",
            status="succeeded",
            llm_provider=getattr(provider, "provider_name", settings.llm_provider),
            llm_model=settings.llm_model,
            prompt_version="fulltext_template_direct.v1",
            candidate_spans_json=json.dumps(candidate_payload, ensure_ascii=False),
            parsed_result_json=json.dumps(result_payload, ensure_ascii=False),
        )
        self.db.add(fulltext_result)
        self.db.flush()
        item.queue_status = "analyzed"
        candidate_payload.update(
            self._maybe_save_llm_debug_files(
                prompt_text=request.prompt_text or "",
                raw_response_text=raw_response_text,
                normalized_response=result_payload,
                fulltext_result=fulltext_result,
                analysis_scope="fulltext_template_direct",
                task_id=task_id,
                provider=provider,
            )
        )
        fulltext_result.candidate_spans_json = json.dumps(
            candidate_payload,
            ensure_ascii=False,
        )
        self.db.commit()
        self.db.refresh(fulltext_result)
        TemplateDirectPersistenceService(self.db).persist(fulltext_result.id)
        self.db.refresh(fulltext_result)
        return fulltext_result

    def _adjudicate_direct_evidences(
        self,
        *,
        item: DeepAnalysisQueueItem,
        provider,
        payload: dict,
        active_templates: List,
    ) -> dict:
        """Run evidence-scoped semantic template judgments when supported."""
        normalized = dict(payload)
        evidences = [
            dict(evidence)
            for evidence in payload.get("evidences", []) or []
            if isinstance(evidence, dict)
        ]
        if not active_templates or not getattr(
            provider,
            "supports_template_adjudication",
            False,
        ):
            normalized["evidences"] = evidences
            return normalized

        active_ids = {int(template.id) for template in active_templates}
        template_fragment = format_template_snapshots_for_prompt(active_templates)
        for evidence in evidences:
            evidence["extraction_matched_template_ids"] = list(
                evidence.get("matched_template_ids") or []
            )
            evidence["extraction_template_satisfied"] = evidence.get(
                "template_satisfied"
            )
            if evidence.get("grounding_status") in {
                "mismatch",
                "attribution_conflict",
            } or str(evidence.get("claim_type") or "") == "false_positive":
                evidence["template_decision_source"] = (
                    "deterministic_grounding_rejection"
                )
                evidence["matched_template_ids"] = []
                evidence["template_satisfied"] = False
                continue

            request = LlmCitationAnalysisRequest(
                target_title=item.cited_paper_title,
                citing_paper_title=item.citing_paper_title,
                cited_paper_title=item.cited_paper_title,
                analysis_scope="template_direct_adjudication",
                prompt_text=build_template_direct_adjudication_prompt(
                    citing_paper_title=item.citing_paper_title,
                    cited_paper_title=item.cited_paper_title,
                    target_reference_marker=str(
                        evidence.get("target_reference_marker")
                        or normalized.get("target_reference_marker")
                        or ""
                    ),
                    target_reference_entry=str(
                        evidence.get("evidence_reference_entry_raw")
                        or normalized.get("target_reference_entry")
                        or ""
                    ),
                    evidence=evidence,
                    template_prompt_fragments=[template_fragment],
                ),
            )
            try:
                decision = self._analyze_direct_with_transient_retries(
                    provider,
                    request,
                ).model_dump()
            except ProviderException as exc:
                evidence["template_decision_source"] = (
                    "template_adjudication_failed"
                )
                evidence["template_adjudication_error"] = exc.code.value
                evidence["recommendation"] = "review"
                evidence["final_recommendation"] = "review"
                continue

            adjudications = [
                adjudication
                for adjudication in decision.get("adjudications", [])
                if isinstance(adjudication, dict)
                and int(adjudication.get("template_id") or 0) in active_ids
            ]
            matched = [
                int(adjudication["template_id"])
                for adjudication in adjudications
                if adjudication.get("satisfied") is True
            ]
            reasons = [
                str(adjudication.get("reason") or "").strip()
                for adjudication in adjudications
                if adjudication.get("satisfied") is True
                and str(adjudication.get("reason") or "").strip()
            ]
            failures = [
                str(adjudication.get("reason") or "").strip()
                for adjudication in adjudications
                if adjudication.get("satisfied") is not True
                and str(adjudication.get("reason") or "").strip()
            ]
            evidence.update(
                {
                    "matched_template_ids": matched,
                    "template_satisfied": bool(matched),
                    "template_match_reason": "; ".join(reasons),
                    "template_failure_reason": "; ".join(failures),
                    "template_relation": str(
                        decision.get("template_relation")
                        or evidence.get("template_relation")
                        or "unmatched"
                    ),
                    "template_adjudications": adjudications,
                    "template_decision_source": "evidence_scoped_llm",
                    "rejudge_version": "template_adjudication.v1",
                }
            )
            if str(decision.get("why_this_judgment_zh") or "").strip():
                evidence["why_this_judgment_zh"] = decision[
                    "why_this_judgment_zh"
                ]
            if str(decision.get("copy_ready_zh") or "").strip():
                evidence["copy_ready_zh"] = decision["copy_ready_zh"]
        normalized["evidences"] = evidences
        normalized["template_adjudication_version"] = (
            "template_adjudication.v1"
        )
        return normalized

    def _analyze_direct_with_transient_retries(self, provider, request):
        max_retries = max(0, int(settings.llm_transient_max_retries))
        backoff_seconds = max(
            0.0,
            float(settings.llm_retry_backoff_seconds),
        )
        for attempt in range(max_retries + 1):
            try:
                return provider.analyze_citation(request)
            except ProviderException as exc:
                if exc.code not in RETRYABLE_ERROR_CODES or attempt >= max_retries:
                    raise
                time.sleep(backoff_seconds * (2**attempt))
        raise AssertionError("unreachable")

    def _direct_template_failure_distribution(self, evidences: List[dict]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for evidence in evidences:
            reason = str(evidence.get("template_failure_reason") or "").strip()
            if not reason:
                continue
            for part in [value.strip() for value in reason.split(";") if value.strip()]:
                counts[part] = counts.get(part, 0) + 1
        return counts

    def _direct_filter_reason_distribution(
        self,
        evidences: Iterable[dict],
    ) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for evidence in evidences or []:
            if not isinstance(evidence, dict):
                continue
            if str(evidence.get("recommendation") or "") == "include":
                continue
            reason_codes = (
                evidence.get("filter_reason_codes", [])
                or evidence.get("failure_reason_codes", [])
                or evidence.get("template_failure_reason_codes", [])
                or direct_evidence_failure_reason_codes(evidence)
            )
            for code in reason_codes:
                normalized = str(code or "").strip()
                if normalized:
                    counts[normalized] = counts.get(normalized, 0) + 1
        return counts

    def _merge_reason_counts(
        self,
        target: Dict[str, int],
        source: Dict[str, int],
    ) -> None:
        for reason, count in source.items():
            target[reason] = int(target.get(reason) or 0) + int(count or 0)

    def _apply_active_templates_to_direct_payload(
        self,
        *,
        item: DeepAnalysisQueueItem,
        payload: dict,
        active_templates: List,
    ) -> dict:
        if not active_templates:
            normalized = dict(payload)
            normalized["evidences"] = [
                {
                    **evidence,
                    "matched_template_ids": [],
                    "matched_template_names": [],
                    "matched_template_types": [],
                    "strong_matched_template_ids": [],
                    "template_satisfied": False,
                    "template_strongly_satisfied": False,
                    "template_match_level": "none",
                    "template_match_reason": "",
                    "template_failure_reason": "no active template covers this candidate",
                    "template_evaluations": [],
                    "final_recommendation": str(
                        evidence.get("recommendation") or "review"
                    ),
                    "final_claim_type": str(
                        evidence.get("claim_type") or "ordinary_reference"
                    ),
                    "filter_reason_codes": direct_evidence_failure_reason_codes(
                        evidence
                    ),
                    "failure_reason_codes": direct_evidence_failure_reason_codes(
                        evidence
                    ),
                }
                for evidence in payload.get("evidences", []) or []
                if isinstance(evidence, dict)
            ]
            return normalized
        normalized = dict(payload)
        normalized_evidences = []
        templates_by_id = {template.id: template for template in active_templates}
        for evidence in payload.get("evidences", []) or []:
            if not isinstance(evidence, dict):
                continue
            updated = dict(evidence)
            template_result = self._direct_model_template_result(
                active_templates,
                updated,
            )
            template_decision_source = (
                "evidence_scoped_llm"
                if updated.get("template_decision_source")
                == "evidence_scoped_llm"
                else "llm"
            )
            if template_result is None:
                template_decision_source = "llm_missing_template_decision"
                template_result = self._missing_direct_model_template_result(
                    active_templates
                )
            updated.update(
                {
                    "matched_template_ids": template_result.get("matched_template_ids", []),
                    "matched_template_names": template_result.get("matched_template_names", []),
                    "strong_matched_template_ids": template_result.get(
                        "strong_matched_template_ids", []
                    ),
                    "matched_template_types": [
                        str(evaluation.get("template_type") or "")
                        for evaluation in template_result.get("template_evaluations", [])
                        if evaluation.get("template_satisfied")
                    ],
                    "strong_matched_template_types": [
                        str(evaluation.get("template_type") or "")
                        for evaluation in template_result.get("template_evaluations", [])
                        if evaluation.get("template_strongly_satisfied")
                    ],
                    "template_match_reason": template_result.get("template_match_reason", ""),
                    "template_satisfied": bool(template_result.get("template_satisfied", False)),
                    "template_strongly_satisfied": bool(
                        template_result.get("template_strongly_satisfied", False)
                    ),
                    "template_match_level": str(
                        template_result.get("template_match_level") or "none"
                    ),
                    "template_failure_reason": template_result.get("template_failure_reason", ""),
                    "template_evaluations": template_result.get("template_evaluations", []),
                    "template_decision_source": template_decision_source,
                }
            )
            relation_claim_type = {
                "explicit_positive_evaluation": "positive_evaluation",
                "detailed_method_summary": "method_summary",
                "capability_recognition": "capability_recognition",
                "first_or_seminal_claim": "first_or_seminal_claim",
                "baseline_or_benchmark": "baseline_or_benchmark",
                "theoretical_foundation": "theoretical_foundation",
                "limitation_feedback": "limitation_feedback",
            }.get(str(updated.get("template_relation") or ""))
            if (
                relation_claim_type
                and template_decision_source == "evidence_scoped_llm"
            ):
                updated["claim_type"] = relation_claim_type
            matched_templates = [
                templates_by_id[template_id]
                for template_id in updated["matched_template_ids"]
                if template_id in templates_by_id
            ]
            strong_matched_templates = [
                templates_by_id[template_id]
                for template_id in updated["strong_matched_template_ids"]
                if template_id in templates_by_id
            ]
            auto_include = any(
                bool(self._load_json(template.scoring_rules_json).get("auto_include_in_report", False))
                for template in strong_matched_templates
            )
            updated["template_auto_include"] = auto_include
            if matched_templates:
                updated["template_display_label"] = " / ".join(
                    template.description or template.name for template in matched_templates
                )
            if template_decision_source in {
                "llm",
                "evidence_scoped_llm",
            }:
                self._apply_direct_model_template_recommendation(
                    updated,
                    strong_matched_templates,
                )
            updated["stance"] = self._direct_evidence_stance(
                updated,
                strong_matched_templates,
            )
            if (
                updated.get("recommendation") == "include"
                and active_templates
                and not strong_matched_templates
            ):
                updated["recommendation"] = "review"
            updated["final_recommendation"] = str(
                updated.get("recommendation") or "review"
            )
            updated["final_claim_type"] = str(
                updated.get("claim_type") or "ordinary_reference"
            )
            reason_codes = direct_evidence_failure_reason_codes(updated)
            updated["filter_reason_codes"] = reason_codes
            updated["failure_reason_codes"] = reason_codes
            normalized_evidences.append(updated)
        normalized["evidences"] = self._deduplicate_direct_strong_clusters(
            normalized_evidences
        )
        return normalized

    def _missing_direct_model_template_result(
        self,
        active_templates: List,
    ) -> dict:
        reason = "model did not return a template decision"
        return {
            "matched_template_ids": [],
            "matched_template_names": [],
            "strong_matched_template_ids": [],
            "template_match_reason": "",
            "template_satisfied": False,
            "template_strongly_satisfied": False,
            "template_match_level": "none",
            "template_failure_reason": reason,
            "template_evaluations": [
                {
                    "template_id": template.id,
                    "template_name": template.description or template.name,
                    "template_type": template.template_type,
                    "template_satisfied": False,
                    "template_strongly_satisfied": False,
                    "template_match_level": "none",
                    "template_match_reason": "",
                    "template_failure_reason": reason,
                    "matched_terms": [],
                    "match_score": 0.0,
                }
                for template in active_templates
            ],
        }

    def _deduplicate_direct_strong_clusters(
        self,
        evidences: List[dict],
    ) -> List[dict]:
        """Keep one reportable evidence per marker/template/claim cluster."""
        clustered: Dict[tuple, dict] = {}
        cluster_indexes: Dict[tuple, int] = {}
        output: List[dict] = []
        for evidence in evidences:
            strong_ids = tuple(
                sorted(
                    int(value)
                    for value in evidence.get("strong_matched_template_ids", []) or []
                    if str(value).isdigit()
                )
            )
            if (
                evidence.get("final_recommendation") != "include"
                or not strong_ids
            ):
                output.append(evidence)
                continue
            marker = str(
                evidence.get("evidence_reference_marker")
                or evidence.get("target_reference_marker")
                or ""
            ).strip()
            key = (
                marker,
                str(evidence.get("final_claim_type") or "").strip(),
                strong_ids,
            )
            current = clustered.get(key)
            if current is None:
                kept = dict(evidence)
                kept["deduplicated_cluster_size"] = 1
                clustered[key] = kept
                cluster_indexes[key] = len(output)
                output.append(kept)
                continue
            current["deduplicated_cluster_size"] = (
                int(current.get("deduplicated_cluster_size") or 1) + 1
            )
            if self._direct_cluster_evidence_rank(evidence) > (
                self._direct_cluster_evidence_rank(current)
            ):
                replacement = dict(evidence)
                replacement["deduplicated_cluster_size"] = current[
                    "deduplicated_cluster_size"
                ]
                output[cluster_indexes[key]] = replacement
                clustered[key] = replacement
        return output

    def _direct_cluster_evidence_rank(self, evidence: dict) -> tuple:
        confidence_rank = {"high": 3, "medium": 2, "low": 1}
        quote = str(evidence.get("evidence_quote") or "")
        context = str(
            evidence.get("evidence_context")
            or evidence.get("surrounding_context")
            or ""
        )
        return (
            1 if not evidence.get("grouped_citation") else 0,
            1
            if str(evidence.get("attribution_scope") or "") == "single_target"
            else 0,
            confidence_rank.get(str(evidence.get("confidence") or "").lower(), 0),
            len(context),
            len(quote),
        )

    def _direct_model_template_result(
        self,
        active_templates: List,
        evidence: dict,
    ) -> Optional[dict]:
        raw_ids = evidence.get("matched_template_ids")
        raw_satisfied = evidence.get("template_satisfied")
        has_model_decision = (
            raw_satisfied is not None
            or bool(raw_ids)
            or bool(str(evidence.get("template_match_reason") or "").strip())
            or bool(str(evidence.get("template_failure_reason") or "").strip())
        )
        if not has_model_decision:
            return None

        templates_by_id = {template.id: template for template in active_templates}
        matched_ids = []
        for value in raw_ids or []:
            try:
                template_id = int(value)
            except (TypeError, ValueError):
                continue
            if template_id in templates_by_id and template_id not in matched_ids:
                matched_ids.append(template_id)
        if raw_satisfied is False:
            matched_ids = []

        strong_ids = list(matched_ids)
        match_reason = str(evidence.get("template_match_reason") or "").strip()
        failure_reason = str(evidence.get("template_failure_reason") or "").strip()
        evaluations = []
        for template in active_templates:
            matched = template.id in matched_ids
            strong = template.id in strong_ids
            evaluations.append(
                {
                    "template_id": template.id,
                    "template_name": template.description or template.name,
                    "template_type": template.template_type,
                    "template_satisfied": matched,
                    "template_strongly_satisfied": strong,
                    "template_match_level": (
                        "strong" if strong else "candidate" if matched else "none"
                    ),
                    "template_match_reason": match_reason if matched else "",
                    "template_failure_reason": "" if matched else failure_reason,
                    "matched_terms": [],
                    "match_score": 100.0 if strong else 50.0 if matched else 0.0,
                }
            )
        return {
            "matched_template_ids": matched_ids,
            "matched_template_names": [
                templates_by_id[template_id].description
                or templates_by_id[template_id].name
                for template_id in matched_ids
            ],
            "strong_matched_template_ids": strong_ids,
            "template_match_reason": match_reason,
            "template_satisfied": bool(matched_ids),
            "template_strongly_satisfied": bool(strong_ids),
            "template_match_level": (
                "strong" if strong_ids else "candidate" if matched_ids else "none"
            ),
            "template_failure_reason": failure_reason,
            "template_evaluations": evaluations,
        }

    def _apply_direct_model_template_recommendation(
        self,
        evidence: dict,
        strong_matched_templates: List,
    ) -> None:
        grounding_valid = (
            str(evidence.get("grounding_status") or "") == "verified"
            if "grounding_status" in evidence
            else self._direct_reference_status(evidence) == "matched"
        )
        hard_valid = (
            grounding_valid
            and self._direct_reference_status(evidence) == "matched"
            and not evidence.get("reference_attribution_conflict")
            and str(evidence.get("target_anchor_status") or "") != "missing"
            and str(evidence.get("claim_type") or "") != "false_positive"
            and not any(
                reason in str(evidence.get("postprocess_reason") or "")
                for reason in (
                    "reference_only",
                    "title_or_reference_only",
                    "cited_other_reference_marker",
                    "target_anchor_missing",
                    "reference_entry_target_mismatch",
                )
            )
        )
        if not hard_valid:
            evidence["recommendation"] = (
                "review"
                if self._direct_reference_status(evidence) == "unresolved"
                else "exclude"
            )
            evidence["strong_matched_template_ids"] = []
            evidence["template_strongly_satisfied"] = False
            evidence["template_match_level"] = (
                "candidate" if evidence.get("matched_template_ids") else "none"
            )
            return
        if strong_matched_templates:
            evidence["recommendation"] = "include"
            return
        if evidence.get("matched_template_ids"):
            evidence["recommendation"] = "review"

    def _direct_evidence_stance(self, evidence: dict, matched_templates: List) -> str:
        claim_type = str(evidence.get("claim_type") or "")
        if claim_type in {"limitation_feedback", "limitation_or_negative"}:
            return "negative"
        supplied = str(evidence.get("stance") or "").strip().lower()
        if supplied in {"positive", "neutral", "negative", "mixed"}:
            return supplied
        intents = {
            template_stance_intent(template)
            for template in matched_templates
        }
        if "negative" in intents:
            return "negative"
        if "positive" in intents:
            return "positive"
        if "neutral" in intents:
            return "neutral"
        if claim_type in {
            "positive_evaluation",
            "first_or_seminal_claim",
            "detailed_comparison",
            "baseline_or_benchmark",
        }:
            return "positive"
        return "neutral"

    def _build_template_direct_compact_text(
        self,
        *,
        full_text: str,
        reference_anchor,
        target_reference_contexts: List,
    ) -> str:
        sections = [
            ("TITLE_ABSTRACT_INTRO_RELATED_CONCLUSION", self._extract_compact_sections(full_text)),
        ]
        if target_reference_contexts:
            context_lines = []
            for index, context in enumerate(target_reference_contexts, start=1):
                heading = getattr(context, "section_heading", "") or ""
                text = getattr(context, "context_text", "") or ""
                context_lines.append(
                    f"[Context {index}] {heading}\n{text[:1800]}"
                )
            sections.append(("TARGET_REFERENCE_CONTEXTS", "\n\n".join(context_lines)))
        if reference_anchor is not None:
            sections.append(
                (
                    "TARGET_REFERENCE_ENTRY",
                    getattr(reference_anchor, "reference_entry_text", "") or "",
                )
            )
        compact = "\n\n".join(
            f"## {title}\n{body.strip()}"
            for title, body in sections
            if str(body or "").strip()
        )
        limit = max(4000, settings.fulltext_direct_max_chars - 4000)
        return compact[:limit]

    def _extract_compact_sections(self, full_text: str) -> str:
        body_end = self._references_start(full_text)
        body_text = full_text[:body_end] if body_end is not None else full_text
        lines = []
        first_chunk = body_text[:4000].strip()
        if first_chunk:
            lines.append("## BEGINNING\n" + first_chunk)
        section_pattern = re.compile(
            r"(?ims)^\s*((abstract|introduction|related work|background|conclusion|conclusions)\b.*?)\n(?=\s*(?:\d+\.|[IVX]+\.)?\s*[A-Z][^\n]{0,80}\n|$)"
        )
        for match in section_pattern.finditer(body_text):
            section = match.group(1).strip()
            if section and section not in lines:
                lines.append(section[:5000])
        return "\n\n".join(lines)

    def _references_start(self, full_text: str) -> Optional[int]:
        match = re.search(r"(?im)^\s*(references|bibliography)\s*$", full_text or "")
        return match.start() if match else None

    def _save_evidence(
        self,
        *,
        finding,
        item: DeepAnalysisQueueItem,
        fulltext_result: FulltextAnalysisResult,
        candidate_spans: List,
        is_self_citation: bool,
        score_value: float,
        evidence_strength: str,
        evidence_reason: str,
        anchor_status: str,
        template_result: Optional[dict] = None,
    ) -> StrongEvidence:
        keywords = build_highlight_keywords(
            citation_text=self._finding_attr(finding, "citation_text", ""),
            keywords=self._finding_attr(finding, "keywords", []),
        )
        return self.evidence_service.upsert_scholar_evidence(
            fulltext_result_id=fulltext_result.id,
            scholar_session_id=item.scholar_session_id,
            queue_item_id=item.id,
            citation_edge_id=item.citation_edge_id,
            aspect=self._finding_attr(finding, "evidence_type", ""),
            stance=self._finding_attr(finding, "stance", ""),
            mention_type=self._finding_attr(finding, "mention_type", ""),
            citation_text=self._finding_attr(finding, "citation_text", ""),
            highlight_keywords=keywords,
            evidence_reason=evidence_reason,
            evidence_strength=evidence_strength,
            score=score_value,
            span_index=self._span_index(
                self._finding_attr(finding, "citation_text", ""),
                [span.text for span in candidate_spans],
            ),
            is_self_citation=is_self_citation,
            third_party_status=item.third_party_status,
            anchor_status=anchor_status,
            template_result=template_result,
        )

    def _template_context_for_finding(
        self,
        *,
        citation_text: str,
        target_reference_contexts,
    ) -> str:
        for context in target_reference_contexts or []:
            if citation_text and citation_text in context.context_text:
                return context.context_text
        return citation_text or ""

    def _should_save_grouped_review_finding(self, finding) -> bool:
        return (
            self._finding_attr(finding, "mention_type", "") == "grouped_citation"
            and self._finding_attr(finding, "evidence_type", "") in GROUPED_REVIEWABLE_TYPES
            and bool((self._finding_attr(finding, "citation_text", "") or "").strip())
        )

    def _should_save_representative_work(
        self,
        *,
        evidence_type: str,
        mention_type: str,
        citation_text: str,
        reasoning: str,
        citation_text_contains_target_marker: bool,
    ) -> bool:
        if not citation_text_contains_target_marker:
            return False
        if mention_type not in {"related_work", "grouped_citation"}:
            return False
        if evidence_type not in {"background", "representative_work"}:
            return False
        normalized_text = self._normalize_text(citation_text)
        normalized_reasoning = self._normalize_text(reasoning)
        representative_terms = {
            "representative",
            "related work",
            "technical line",
            "method category",
            "prior work",
            "technology route",
            "field positioning",
            "research direction",
            "category",
            "example",
        }
        return any(
            term in normalized_text or term in normalized_reasoning
            for term in representative_terms
        )

    def _background_anchor_upgrade_type(self, *, citation_text: str, reasoning: str) -> Optional[str]:
        normalized = self._normalize_text(f"{citation_text} {reasoning}")
        limitation_terms = (
            "limitation",
            "limitations",
            "addressing limitation",
            "addressing limitations",
            "camera dependent",
            "camera dependent",
            "sensitive to lighting",
            "lighting sensitive",
            "design trade off",
            "design trade offs",
            "design trade-off",
            "design trade-offs",
            "design tradeoff",
            "design tradeoffs",
            "trade off",
            "trade offs",
            "trade-off",
            "trade-offs",
            "tradeoff",
            "tradeoffs",
            "drawback",
            "weakness",
            "constraint",
            "negative",
        )
        comparison_terms = (
            "compared with",
            "compared to",
            "comparison",
            "compare",
            "outperform",
            "superiority",
            "advantage",
            "benchmark",
            "baseline",
        )
        mechanism_terms = (
            "introduces",
            "introduced",
            "proposes",
            "proposed",
            "presents",
            "presented",
            "mechanism",
            "method",
            "approach",
            "framework",
            "model",
            "system",
        )
        if any(term in normalized for term in limitation_terms):
            return "limitation_or_negative"
        if any(term in normalized for term in comparison_terms):
            return "detailed_comparison"
        if any(term in normalized for term in mechanism_terms):
            return "representative_work"
        return None

    def _override_finding_type(self, finding, evidence_type: str):
        return self._override_finding_fields(finding, evidence_type=evidence_type)

    def _override_finding_fields(self, finding, **updates):
        if hasattr(finding, "model_copy"):
            return finding.model_copy(update=updates)
        snapshot = self._finding_snapshot(finding)
        snapshot.update(updates)
        from app.schemas.llm import LlmFinding

        return LlmFinding.model_validate(snapshot)

    def _override_finding_citation_text(self, finding, citation_text: str):
        if hasattr(finding, "model_copy"):
            return finding.model_copy(update={"citation_text": citation_text})
        snapshot = self._finding_snapshot(finding)
        snapshot["citation_text"] = citation_text
        from app.schemas.llm import LlmFinding

        return LlmFinding.model_validate(snapshot)

    def _expand_to_target_anchor_sentence(
        self,
        *,
        citation_text: str,
        full_text: str,
        reference_anchor,
    ) -> str:
        if not citation_text or reference_anchor is None:
            return ""
        if citation_text_has_target_anchor(citation_text, reference_anchor.reference_marker):
            return citation_text
        if re.search(r"\[[^\]]*\d+[^\]]*\]", citation_text):
            return ""
        quote_index = full_text.find(citation_text)
        if quote_index < 0:
            return ""
        sentence_start = max(
            full_text.rfind(".", 0, quote_index),
            full_text.rfind("!", 0, quote_index),
            full_text.rfind("?", 0, quote_index),
            full_text.rfind("\n", 0, quote_index),
        )
        sentence_start = 0 if sentence_start < 0 else sentence_start + 1
        following_bounds = [
            idx
            for idx in (
                full_text.find(".", quote_index + len(citation_text)),
                full_text.find("!", quote_index + len(citation_text)),
                full_text.find("?", quote_index + len(citation_text)),
                full_text.find("\n", quote_index + len(citation_text)),
            )
            if idx >= 0
        ]
        sentence_end = min(following_bounds) + 1 if following_bounds else len(full_text)
        sentence = full_text[sentence_start:sentence_end].strip()
        if citation_text_has_target_anchor(sentence, reference_anchor.reference_marker):
            return sentence
        return ""

    def _anchor_status_for_finding(
        self,
        *,
        mention_type: str,
        citation_text: str,
        reference_anchor,
        in_target_reference_context: bool,
    ) -> str:
        if mention_type == "grouped_citation":
            return "grouped_citation"
        if citation_text_has_target_anchor(
            citation_text,
            reference_anchor.reference_marker if reference_anchor else None,
        ) or in_target_reference_context:
            return "body_anchor_found"
        return "nearby_body_anchor"

    def _build_result_diagnostics_payload(
        self,
        *,
        analysis_scope: str,
        extracted_text: str,
        candidate_spans: List,
        finding_diagnostics: List[Dict[str, object]],
        normalized_findings: List[Dict[str, object]],
        prompt_text: str,
        raw_response_text: str,
        fulltext_result: FulltextAnalysisResult,
        task_id: Optional[int],
        provider,
        reference_anchor,
        target_reference_contexts,
        target_alias_contexts,
        active_templates,
        template_snapshot_json: str,
    ) -> Dict[str, object]:
        satisfied_count = sum(
            1
            for item in finding_diagnostics
            if item.get("template_satisfied")
        )
        unsatisfied_count = sum(
            1
            for item in finding_diagnostics
            if not item.get("template_satisfied") and item.get("template_evaluations")
        )
        payload = {
            "mode": analysis_scope,
            "fulltext_chars": len(extracted_text),
            "llm_findings_count": len(finding_diagnostics),
            "generated_strong_evidence_count": sum(
                1 for item in finding_diagnostics if item.get("generated_strong_evidence")
            ),
            "filtered_findings_count": sum(
                1 for item in finding_diagnostics if not item.get("generated_strong_evidence")
            ),
            "filter_reason_distribution": self._finding_reason_distribution(finding_diagnostics),
            "finding_diagnostics": finding_diagnostics,
            "prompt_debug_enabled": bool(
                getattr(settings, "debug_save_llm_prompts", False)
            ),
            "prompt_chars": len(prompt_text or ""),
            "raw_response_chars": len(raw_response_text or ""),
            "reference_anchor_found": reference_anchor is not None,
            "reference_anchor_reason": reference_anchor.match_method if reference_anchor else "not_found",
            "target_reference_marker": (
                reference_anchor.reference_marker_text if reference_anchor else ""
            ),
            "target_reference_context_count": len(target_reference_contexts or []),
            "target_alias_context_count": len(target_alias_contexts or []),
            "target_contexts_preview": [
                {
                    "section_heading": context.section_heading,
                    "context_type": context.context_type,
                    "contains_formula": context.contains_formula,
                    "context_text_preview": self._truncate(context.context_text, 400),
                }
                for context in (target_reference_contexts or [])[:5]
            ],
            "alias_contexts_preview": [
                {
                    "section_heading": context.section_heading,
                    "context_type": context.context_type,
                    "contains_formula": context.contains_formula,
                    "context_text_preview": self._truncate(context.context_text, 280),
                }
                for context in (target_alias_contexts or [])[:5]
            ],
            "prompt_contains_target_contexts": bool(target_reference_contexts),
            "active_template_count": len(active_templates or []),
            "active_template_names": [
                template.description or template.name for template in (active_templates or [])
            ],
            "prompt_contains_templates": bool(active_templates),
            "prompt_template_snapshot_json": template_snapshot_json,
            "template_satisfied_count": satisfied_count,
            "template_unsatisfied_count": unsatisfied_count,
            "template_failure_reason_distribution": self._template_failure_reason_distribution(
                finding_diagnostics
            ),
        }
        if analysis_scope == "fulltext_direct":
            payload["max_chars"] = settings.fulltext_direct_max_chars
            payload["target_reference_entry"] = (
                reference_anchor.reference_entry_text if reference_anchor else ""
            )
        else:
            payload["candidate_spans_count"] = len(candidate_spans)
            payload["spans"] = [
                {"text": span.text, "start": span.start, "end": span.end}
                for span in candidate_spans
            ]
        payload.update(
            self._maybe_save_llm_debug_files(
                prompt_text=prompt_text,
                raw_response_text=raw_response_text,
                normalized_response={
                    "findings": normalized_findings,
                    "finding_diagnostics": [
                        self._finding_to_dict(item) for item in finding_diagnostics
                    ],
                },
                fulltext_result=fulltext_result,
                analysis_scope=analysis_scope,
                task_id=task_id,
                provider=provider,
            )
        )
        return payload

    def _provider_raw_response(self, provider, parsed_result: CitationAnalysisResponse) -> str:
        raw_response = getattr(provider, "last_raw_response_text", "") or ""
        if raw_response:
            return self._redact_sensitive(raw_response)
        return self._redact_sensitive(parsed_result.model_dump_json())

    def _maybe_save_llm_debug_files(
        self,
        *,
        prompt_text: str,
        raw_response_text: str,
        normalized_response: Dict[str, object],
        fulltext_result: FulltextAnalysisResult,
        analysis_scope: str,
        task_id: Optional[int],
        provider,
    ) -> Dict[str, object]:
        if not getattr(settings, "debug_save_llm_prompts", False):
            return {}
        debug_dir = self._debug_llm_dir() / f"result_{fulltext_result.id}"
        debug_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = debug_dir / "prompt.txt"
        raw_response_file = debug_dir / "raw_response.txt"
        normalized_response_file = debug_dir / "normalized_response.json"
        metadata_file = debug_dir / "metadata.json"
        prompt_file.write_text(self._redact_sensitive(prompt_text), encoding="utf-8")
        raw_response_file.write_text(
            self._redact_sensitive(raw_response_text),
            encoding="utf-8",
        )
        normalized_response_file.write_text(
            json.dumps(normalized_response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metadata_file.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "scholar_session_id": fulltext_result.scholar_session_id,
                    "queue_item_id": fulltext_result.queue_item_id,
                    "fulltext_result_id": fulltext_result.id,
                    "analysis_scope": analysis_scope,
                    "llm_provider": getattr(provider, "provider_name", settings.llm_provider),
                    "llm_model": settings.llm_model,
                    "prompt_version": fulltext_result.prompt_version,
                    "prompt_chars": len(prompt_text or ""),
                    "response_chars": len(raw_response_text or ""),
                    "created_at": datetime.utcnow().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "prompt_debug_file": prompt_file.name,
            "raw_response_debug_file": raw_response_file.name,
            "normalized_response_debug_file": normalized_response_file.name,
            "metadata_debug_file": metadata_file.name,
        }

    def _debug_llm_dir(self) -> Path:
        path = Path(getattr(settings, "debug_llm_dir", "./var/debug/llm_prompts"))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def _finding_reason_distribution(
        self,
        finding_diagnostics: List[Dict[str, object]],
    ) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for finding in finding_diagnostics:
            reason = str(finding.get("filter_reason") or "unknown")
            counts[reason] = counts.get(reason, 0) + 1
        return counts

    def _template_failure_reason_distribution(
        self,
        finding_diagnostics: List[Dict[str, object]],
    ) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for finding in finding_diagnostics:
            for evaluation in finding.get("template_evaluations", []) or []:
                if evaluation.get("template_satisfied"):
                    continue
                reason = str(evaluation.get("template_failure_reason") or "unknown")
                counts[reason] = counts.get(reason, 0) + 1
        return counts

    def _merge_template_diagnostics_into_findings(
        self,
        findings: List[Dict[str, object]],
        diagnostics: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        merged: List[Dict[str, object]] = []
        for index, finding in enumerate(findings):
            payload = dict(finding)
            diagnostic = diagnostics[index] if index < len(diagnostics) else {}
            for key in [
                "matched_template_ids",
                "matched_template_names",
                "template_match_reason",
                "template_satisfied",
                "template_failure_reason",
                "template_evaluations",
            ]:
                payload[key] = diagnostic.get(key, payload.get(key))
            merged.append(payload)
        return merged

    def _finding_to_dict(self, finding_diagnostic: Dict[str, object]) -> Dict[str, object]:
        return {
            "finding_index": finding_diagnostic.get("finding_index"),
            "citation_text_preview": finding_diagnostic.get("citation_text_preview"),
            "evidence_type": finding_diagnostic.get("evidence_type"),
            "stance": finding_diagnostic.get("stance"),
            "mention_type": finding_diagnostic.get("mention_type"),
            "target_reference_marker": finding_diagnostic.get("target_reference_marker"),
            "citation_text_contains_target_marker": finding_diagnostic.get(
                "citation_text_contains_target_marker"
            ),
            "citation_text_in_target_context": finding_diagnostic.get(
                "citation_text_in_target_context"
            ),
            "filter_reason": finding_diagnostic.get("filter_reason"),
            "generated_strong_evidence": finding_diagnostic.get("generated_strong_evidence"),
            "reasoning": finding_diagnostic.get("reasoning"),
            "promotion_decision": finding_diagnostic.get("promotion_decision"),
            "evidence_strength_if_saved": finding_diagnostic.get("evidence_strength_if_saved"),
            "needs_human_review": finding_diagnostic.get("needs_human_review"),
            "matched_template_ids": finding_diagnostic.get("matched_template_ids", []),
            "matched_template_names": finding_diagnostic.get("matched_template_names", []),
            "template_match_reason": finding_diagnostic.get("template_match_reason", ""),
            "template_satisfied": finding_diagnostic.get("template_satisfied"),
            "template_failure_reason": finding_diagnostic.get("template_failure_reason", ""),
        }

    def _result_payload(self, parsed_result) -> Dict[str, object]:
        if hasattr(parsed_result, "model_dump"):
            return parsed_result.model_dump()
        if hasattr(parsed_result, "model_dump_json"):
            try:
                return json.loads(parsed_result.model_dump_json())
            except (TypeError, json.JSONDecodeError):
                pass
        return {
            "findings": [
                self._finding_snapshot(finding)
                for finding in getattr(parsed_result, "findings", [])
            ]
        }

    def _finding_snapshot(self, finding) -> Dict[str, object]:
        return {
            "evidence_type": self._finding_attr(finding, "evidence_type", ""),
            "stance": self._finding_attr(finding, "stance", ""),
            "mention_type": self._finding_attr(finding, "mention_type", ""),
            "citation_text": self._finding_attr(finding, "citation_text", ""),
            "reasoning": self._finding_attr(finding, "reasoning", ""),
            "keywords": self._finding_attr(finding, "keywords", []),
            "keep": self._finding_attr(finding, "keep", True),
            "matched_template_ids": self._finding_attr(finding, "matched_template_ids", []),
            "template_match_reason": self._finding_attr(finding, "template_match_reason", ""),
            "template_satisfied": self._finding_attr(finding, "template_satisfied", None),
            "template_failure_reason": self._finding_attr(finding, "template_failure_reason", None),
        }

    def _finding_attr(self, finding, name: str, default):
        value = getattr(finding, name, default)
        return default if value is None else value

    def list_scholar_evidence(
        self,
        session_id: int,
        *,
        filters: Optional[Dict[str, str]] = None,
        pagination: Optional[dict] = None,
    ) -> List[dict]:
        return self.evidence_service.list_scholar_evidence(
            session_id,
            filters=filters,
            pagination=pagination,
        )

    def latest_direct_candidate_layers(
        self,
        session_id: int,
    ) -> Dict[str, object]:
        results = list(
            self.db.scalars(
                select(FulltextAnalysisResult)
                .where(
                    FulltextAnalysisResult.scholar_session_id == session_id,
                    FulltextAnalysisResult.analysis_scope
                    == "fulltext_template_direct",
                    FulltextAnalysisResult.status == "succeeded",
                )
                .order_by(
                    FulltextAnalysisResult.created_at.desc(),
                    FulltextAnalysisResult.id.desc(),
                )
            )
        )
        latest_results = []
        seen_queue_items = set()
        for result in results:
            if result.queue_item_id in seen_queue_items:
                continue
            seen_queue_items.add(result.queue_item_id)
            latest_results.append(result)
        layers: Dict[str, object] = {
            "result_id": None,
            "result_ids": [],
            "result_count": 0,
            "strong": [],
            "review": [],
            "excluded": [],
            "counts": {
                "strong": 0,
                "review": 0,
                "excluded": 0,
            },
            "verified_count": 0,
            "verified_substantive_count": 0,
        }
        if not latest_results:
            return layers
        for result in latest_results:
            payload = self._load_json(result.parsed_result_json)
            for evidence in payload.get("evidences", []) or []:
                if not isinstance(evidence, dict):
                    continue
                row = self._direct_candidate_view_row(evidence)
                row["result_id"] = result.id
                row["queue_item_id"] = result.queue_item_id
                recommendation = str(row["recommendation"])
                key = (
                    "strong"
                    if recommendation == "include"
                    else "review"
                    if recommendation == "review"
                    else "excluded"
                )
                layers[key].append(row)
        layers["result_id"] = latest_results[0].id
        layers["result_ids"] = [result.id for result in latest_results]
        layers["result_count"] = len(latest_results)
        layers["counts"] = {
            key: len(layers[key])
            for key in ("strong", "review", "excluded")
        }
        all_rows = (
            layers["strong"] + layers["review"] + layers["excluded"]
        )
        layers["verified_count"] = sum(
            1 for row in all_rows if row.get("grounding_status") == "verified"
        )
        layers["verified_substantive_count"] = sum(
            1
            for row in all_rows
            if row.get("grounding_status") == "verified"
            and row.get("template_relation") != "unmatched"
        )
        layers["strong_stance_counts"] = {
            stance: sum(
                1
                for evidence in layers["strong"]
                if evidence.get("stance") == stance
            )
            for stance in ("positive", "neutral", "negative")
        }
        return layers

    def _direct_candidate_view_row(self, evidence: dict) -> Dict[str, object]:
        reason_codes = direct_evidence_failure_reason_codes(evidence)
        alignment = self._direct_reference_status(evidence)
        if alignment != "matched":
            missing_dimension = "引用对齐未完成"
        elif not evidence.get("matched_template_ids"):
            missing_dimension = self._direct_missing_template_dimension(evidence)
        elif evidence.get("template_satisfied") is not True:
            missing_dimension = "模板严格条件未满足"
        else:
            missing_dimension = ""
        return {
            "recommendation": self._final_direct_recommendation(evidence),
            "claim_type": str(
                evidence.get("final_claim_type")
                or evidence.get("claim_type")
                or "ordinary_reference"
            ),
            "stance": self._direct_evidence_stance(evidence, []),
            "evidence_quote": str(evidence.get("evidence_quote") or ""),
            "evidence_context": str(
                evidence.get("evidence_context")
                or evidence.get("surrounding_context")
                or ""
            ),
            "reference_marker": str(
                evidence.get("evidence_reference_marker")
                or evidence.get("target_reference_marker")
                or ""
            ),
            "reference_alignment_status": alignment or "unresolved",
            "grounding_status": str(
                evidence.get("grounding_status") or "unresolved"
            ),
            "evidence_strength": str(
                evidence.get("evidence_strength") or "weak"
            ),
            "template_relation": str(
                evidence.get("template_relation") or "unmatched"
            ),
            "matched_template_names": list(
                evidence.get("matched_template_names") or []
            ),
            "template_failure_reason": str(
                evidence.get("template_failure_reason") or ""
            ),
            "filter_reason_codes": reason_codes,
            "missing_dimension": missing_dimension,
        }

    def _direct_missing_template_dimension(self, evidence: dict) -> str:
        claim_type = str(
            evidence.get("final_claim_type")
            or evidence.get("claim_type")
            or ""
        )
        reason_codes = set(direct_evidence_failure_reason_codes(evidence))
        if "target_marker_missing" in reason_codes:
            return "正文目标引用锚点缺失"
        if "reference_mismatch" in reason_codes:
            return "正文引用与目标参考文献不一致"
        if claim_type in {"ordinary_reference", "ordinary_citation"}:
            return "正文仅为普通或中立引用，当前评价模板未覆盖"
        if claim_type in {
            "method_summary",
            "capability_summary",
            "method_use",
            "capability_recognition",
        }:
            return "正文是方法或能力概述，但未满足当前评价模板的明确条件"
        if claim_type in {"limitation_feedback", "limitation_or_negative"}:
            return "正文含局限性描述，但未满足负面/局限评价模板的锚点或作用域条件"
        return "当前启用模板未覆盖或未满足"

    def list_analysis_diagnostics(self, session_id: int) -> List[Dict[str, object]]:
        statement = (
            select(FulltextAnalysisResult)
            .where(FulltextAnalysisResult.scholar_session_id == session_id)
            .order_by(FulltextAnalysisResult.created_at.desc(), FulltextAnalysisResult.id.desc())
        )
        diagnostics = []
        for result in self.db.scalars(statement):
            candidate_payload = self._load_json(result.candidate_spans_json)
            parsed_payload = self._load_json(result.parsed_result_json)
            direct_counts = self._direct_evidence_counts(parsed_payload)
            is_template_direct = result.analysis_scope == "fulltext_template_direct"
            llm_findings_count = (
                direct_counts["parsed_evidence_count"]
                if is_template_direct
                else self._diagnostic_count(parsed_payload, candidate_payload, "llm_findings_count")
            )
            generated_count = self._diagnostic_count(parsed_payload, candidate_payload, "generated_strong_evidence_count")
            if is_template_direct:
                generated_count = direct_counts["generated_strong_evidence_count"]
            elif generated_count == 0:
                generated_count = self.db.query(StrongEvidence).filter_by(
                    fulltext_result_id=result.id
                ).count()
            persistence_counts = self._direct_persistence_counts(result)
            filtered_count = self._diagnostic_count(parsed_payload, candidate_payload, "filtered_findings_count")
            if filtered_count == 0:
                filtered_count = max(0, llm_findings_count - generated_count)
            filter_reason_distribution = self._diagnostic_value(
                candidate_payload,
                "filter_reason_distribution",
                {},
            )
            if is_template_direct:
                direct_evidences = parsed_payload.get("evidences", [])
                filtered_count = sum(
                    1
                    for evidence in direct_evidences
                    if isinstance(evidence, dict)
                    and evidence.get("recommendation") != "include"
                )
                filter_reason_distribution = (
                    self._direct_filter_reason_distribution(direct_evidences)
                )
            diagnostics.append(
                {
                    "id": result.id,
                    "queue_item_id": result.queue_item_id,
                    "analysis_scope": result.analysis_scope,
                    "status": result.status,
                    "fulltext_chars": (
                        candidate_payload.get("fulltext_chars")
                        if isinstance(candidate_payload, dict)
                        else None
                    ),
                    "llm_findings_count": llm_findings_count,
                    **direct_counts,
                    "generated_strong_evidence_count": generated_count,
                    **persistence_counts,
                    "filtered_findings_count": filtered_count,
                    "filter_reason_distribution": filter_reason_distribution,
                    "finding_diagnostics": self._diagnostic_value(
                        candidate_payload,
                        "finding_diagnostics",
                        [],
                    ),
                    "prompt_debug_enabled": self._diagnostic_value(
                        candidate_payload,
                        "prompt_debug_enabled",
                        False,
                    ),
                    "prompt_chars": self._diagnostic_value(candidate_payload, "prompt_chars"),
                    "raw_response_chars": self._diagnostic_value(candidate_payload, "raw_response_chars"),
                    "prompt_debug_file": self._diagnostic_value(candidate_payload, "prompt_debug_file", ""),
                    "raw_response_debug_file": self._diagnostic_value(candidate_payload, "raw_response_debug_file", ""),
                    "normalized_response_debug_file": self._diagnostic_value(candidate_payload, "normalized_response_debug_file", ""),
                    "metadata_debug_file": self._diagnostic_value(candidate_payload, "metadata_debug_file", ""),
                    "target_reference_marker": self._diagnostic_value(candidate_payload, "target_reference_marker", ""),
                    "target_reference_entry": self._diagnostic_value(candidate_payload, "target_reference_entry", ""),
                    "target_reference_context_count": self._diagnostic_value(candidate_payload, "target_reference_context_count", 0),
                    "target_alias_context_count": self._diagnostic_value(candidate_payload, "target_alias_context_count", 0),
                    "target_contexts_preview": self._diagnostic_value(candidate_payload, "target_contexts_preview", []),
                    "alias_contexts_preview": self._diagnostic_value(candidate_payload, "alias_contexts_preview", []),
                    "prompt_contains_target_contexts": self._diagnostic_value(candidate_payload, "prompt_contains_target_contexts", False),
                    "active_template_count": self._diagnostic_value(candidate_payload, "active_template_count", 0),
                    "active_template_names": self._diagnostic_value(candidate_payload, "active_template_names", []),
                    "prompt_contains_templates": self._diagnostic_value(candidate_payload, "prompt_contains_templates", False),
                    "template_satisfied_count": self._diagnostic_value(candidate_payload, "template_satisfied_count", 0),
                    "template_unsatisfied_count": self._diagnostic_value(candidate_payload, "template_unsatisfied_count", 0),
                    "template_failure_reason_distribution": self._diagnostic_value(candidate_payload, "template_failure_reason_distribution", {}),
                    "prompt_template_snapshot_json": self._diagnostic_value(candidate_payload, "prompt_template_snapshot_json", ""),
                    "is_fulltext_direct_empty": (
                        result.analysis_scope in {
                            "fulltext_direct",
                            "fulltext_anchor_direct",
                            "fulltext_template_direct",
                        }
                        and isinstance(parsed_payload, dict)
                        and (
                            direct_counts["parsed_evidence_count"] == 0
                            if is_template_direct
                            else len(parsed_payload.get("findings", [])) == 0
                        )
                    ),
                    "raw_output_preview": self._redact_sensitive(
                        parsed_payload.get("raw_output_preview", "")
                    )
                    if isinstance(parsed_payload, dict)
                    else "",
                    "schema_error": self._redact_sensitive(
                        parsed_payload.get("schema_error", "")
                    )
                    if isinstance(parsed_payload, dict)
                    else "",
                    "prompt_preview": self._debug_file_preview(
                        self._diagnostic_value(candidate_payload, "prompt_debug_file", ""),
                        result_id=result.id,
                    ),
                    "error_message": result.error_message,
                }
            )
        return diagnostics

    def list_analysis_debug_rows(self, session_id: int, limit: int = 10) -> List[Dict[str, object]]:
        statement = (
            select(FulltextAnalysisResult)
            .where(FulltextAnalysisResult.scholar_session_id == session_id)
            .order_by(FulltextAnalysisResult.created_at.desc(), FulltextAnalysisResult.id.desc())
            .limit(limit)
        )
        rows = []
        for result in self.db.scalars(statement):
            candidate_payload = self._load_json(result.candidate_spans_json)
            parsed_payload = self._load_json(result.parsed_result_json)
            item = self.db.get(DeepAnalysisQueueItem, result.queue_item_id) if result.queue_item_id else None
            findings = (
                parsed_payload.get("findings")
                or parsed_payload.get("evidences")
                or []
            ) if isinstance(parsed_payload, dict) else []
            direct_counts = self._direct_evidence_counts(parsed_payload)
            generated_count = self._diagnostic_count(parsed_payload, candidate_payload, "generated_strong_evidence_count")
            if result.analysis_scope == "fulltext_template_direct":
                generated_count = direct_counts["generated_strong_evidence_count"]
            elif generated_count == 0:
                generated_count = self.db.query(StrongEvidence).filter_by(
                    fulltext_result_id=result.id
                ).count()
            persistence_counts = self._direct_persistence_counts(result)
            filtered_count = self._diagnostic_count(parsed_payload, candidate_payload, "filtered_findings_count")
            if filtered_count == 0:
                filtered_count = max(0, len(findings) - generated_count)
            filter_reason_distribution = self._diagnostic_value(
                candidate_payload,
                "filter_reason_distribution",
                {},
            )
            if result.analysis_scope == "fulltext_template_direct":
                direct_evidences = parsed_payload.get("evidences", [])
                filtered_count = sum(
                    1
                    for evidence in direct_evidences
                    if isinstance(evidence, dict)
                    and evidence.get("recommendation") != "include"
                )
                filter_reason_distribution = (
                    self._direct_filter_reason_distribution(direct_evidences)
                )
            rows.append(
                {
                    "id": result.id,
                    "queue_item_id": result.queue_item_id,
                    "citing_paper_title": item.citing_paper_title if item else "",
                    "cited_paper_title": item.cited_paper_title if item else "",
                    "analysis_scope": result.analysis_scope,
                    "fulltext_chars": self._diagnostic_value(candidate_payload, "fulltext_chars"),
                    "prompt_chars": self._diagnostic_value(candidate_payload, "prompt_chars"),
                    "llm_provider": result.llm_provider or "",
                    "llm_model": result.llm_model or "",
                    "status": result.status,
                    "error_message": result.error_message,
                    "llm_findings_count": len(findings),
                    **direct_counts,
                    "candidate_spans_count": self._candidate_spans_count(candidate_payload),
                    "parsed_findings_preview": self._preview_findings(findings),
                    "generated_strong_evidence_count": generated_count,
                    **persistence_counts,
                    "filtered_findings_count": filtered_count,
                    "filter_reason_distribution": filter_reason_distribution,
                    "finding_diagnostics": self._diagnostic_value(candidate_payload, "finding_diagnostics", []),
                    "raw_output_preview": self._redact_sensitive(
                        parsed_payload.get("raw_output_preview", "")
                    )
                    if isinstance(parsed_payload, dict)
                    else "",
                    "schema_error": self._redact_sensitive(
                        parsed_payload.get("schema_error", "")
                    )
                    if isinstance(parsed_payload, dict)
                    else "",
                    "prompt_debug_file": self._diagnostic_value(candidate_payload, "prompt_debug_file", ""),
                    "response_debug_file": self._diagnostic_value(candidate_payload, "raw_response_debug_file", ""),
                    "normalized_response_debug_file": self._diagnostic_value(candidate_payload, "normalized_response_debug_file", ""),
                    "metadata_debug_file": self._diagnostic_value(candidate_payload, "metadata_debug_file", ""),
                    "target_reference_marker": self._diagnostic_value(candidate_payload, "target_reference_marker", ""),
                    "target_reference_entry": self._diagnostic_value(candidate_payload, "target_reference_entry", ""),
                    "target_reference_context_count": self._diagnostic_value(candidate_payload, "target_reference_context_count", 0),
                    "target_alias_context_count": self._diagnostic_value(candidate_payload, "target_alias_context_count", 0),
                    "target_contexts_preview": self._diagnostic_value(candidate_payload, "target_contexts_preview", []),
                    "alias_contexts_preview": self._diagnostic_value(candidate_payload, "alias_contexts_preview", []),
                    "prompt_contains_target_contexts": self._diagnostic_value(candidate_payload, "prompt_contains_target_contexts", False),
                    "active_template_count": self._diagnostic_value(candidate_payload, "active_template_count", 0),
                    "active_template_names": self._diagnostic_value(candidate_payload, "active_template_names", []),
                    "prompt_contains_templates": self._diagnostic_value(candidate_payload, "prompt_contains_templates", False),
                    "template_satisfied_count": self._diagnostic_value(candidate_payload, "template_satisfied_count", 0),
                    "template_unsatisfied_count": self._diagnostic_value(candidate_payload, "template_unsatisfied_count", 0),
                    "template_failure_reason_distribution": self._diagnostic_value(candidate_payload, "template_failure_reason_distribution", {}),
                    "prompt_template_snapshot_json": self._diagnostic_value(candidate_payload, "prompt_template_snapshot_json", ""),
                    "prompt_preview": self._debug_file_preview(
                        self._diagnostic_value(candidate_payload, "prompt_debug_file", ""),
                        result_id=result.id,
                    ),
                }
            )
        return rows

    def update_evidence_review(
        self,
        evidence_id: int,
        review_status: str,
        user_note: str,
        corrected_label: Optional[str] = None,
    ):
        return self.evidence_service.update_evidence_review(
            evidence_id,
            review_status,
            user_note,
            corrected_label,
        )

    def queue_pdf_summary(self, session_id: int) -> Dict[str, int]:
        items = self.db.query(DeepAnalysisQueueItem).filter_by(
            scholar_session_id=session_id
        ).all()
        return {
            "total_queue_items": len(items),
            "ready_count": sum(
                1
                for item in items
                if is_pdf_ready_status(item.pdf_readiness_status)
            ),
            "need_pdf_count": sum(
                1 for item in items if item.pdf_readiness_status == "need_pdf"
            ),
        }

    def _pdf_blocking_reason(self, item: DeepAnalysisQueueItem) -> Optional[str]:
        if not is_pdf_ready_status(item.pdf_readiness_status):
            return "unsupported_pdf_status"
        if not item.pdf_asset_id:
            return "invalid_pdf_binding"
        pdf_asset = self.db.get(PdfAsset, item.pdf_asset_id)
        if pdf_asset is None:
            return "invalid_pdf_binding"
        if pdf_asset.extract_status != "succeeded":
            return "pdf_extract_not_ready"
        if not pdf_asset.extracted_text_path:
            return "missing_extracted_text"
        if not Path(pdf_asset.extracted_text_path).exists():
            return "missing_extracted_text"
        return None

    def enqueue_analyze_queue(
        self,
        *,
        session_id: int,
        queue_item_ids: Optional[List[int]] = None,
        analysis_scope: str = "candidate_spans",
    ):
        analysis_scope = self._normalize_analysis_scope(analysis_scope)
        if queue_item_ids:
            for item in self._list_target_items(session_id, queue_item_ids):
                item.queue_status = "selected"
            self.db.commit()
        task = TaskService(TaskRepository(self.db)).enqueue(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            task_type="analyze_scholar_queue",
            payload={
                "analysis_scope": analysis_scope,
                "queue_item_ids": queue_item_ids or None,
                "queue_item_id": queue_item_ids[0] if queue_item_ids and len(queue_item_ids) == 1 else None,
            },
        )
        task.stage_message = f"analysis_scope={analysis_scope}"
        self.db.commit()
        self.db.refresh(task)
        return task

    def enqueue_rejudge_template_direct_evidences(
        self,
        *,
        session_id: int,
        fulltext_result_ids: Optional[List[int]] = None,
    ):
        task = TaskService(TaskRepository(self.db)).enqueue(
            session_kind=SCHOLAR_ANALYSIS_SESSION_KIND,
            session_id=session_id,
            task_type="rejudge_template_direct_evidences",
            payload={
                "fulltext_result_ids": fulltext_result_ids or None,
                "rejudge_version": "template_adjudication.v1",
            },
        )
        task.stage_message = "等待对已有 direct evidence 重新裁决"
        self.db.commit()
        self.db.refresh(task)
        return task

    def rejudge_template_direct_evidences(
        self,
        *,
        session_id: int,
        fulltext_result_ids: Optional[List[int]] = None,
        task=None,
    ) -> Dict[str, int]:
        statement = (
            select(FulltextAnalysisResult)
            .where(
                FulltextAnalysisResult.scholar_session_id == session_id,
                FulltextAnalysisResult.analysis_scope
                == "fulltext_template_direct",
                FulltextAnalysisResult.status == "succeeded",
            )
            .order_by(
                FulltextAnalysisResult.created_at.desc(),
                FulltextAnalysisResult.id.desc(),
            )
        )
        if fulltext_result_ids:
            statement = statement.where(
                FulltextAnalysisResult.id.in_(fulltext_result_ids)
            )
        results = list(self.db.scalars(statement))
        if not fulltext_result_ids:
            latest = []
            seen_queue_items = set()
            for result in results:
                if result.queue_item_id in seen_queue_items:
                    continue
                seen_queue_items.add(result.queue_item_id)
                latest.append(result)
            results = latest

        active_templates = TemplateService(self.db).get_active_templates(
            session_id
        )
        provider = get_llm_provider()
        if not getattr(provider, "supports_template_adjudication", False):
            raise ValueError(
                "Configured LLM provider does not support template adjudication"
            )
        counts = {
            "result_count": len(results),
            "evidence_count": 0,
            "include_count": 0,
            "review_count": 0,
            "exclude_count": 0,
        }
        for index, result in enumerate(results, start=1):
            item = self.db.get(DeepAnalysisQueueItem, result.queue_item_id)
            if item is None:
                continue
            if task is not None:
                current_task = self.db.get(type(task), task.id)
                current_task.progress_total = len(results)
                current_task.progress_current = index - 1
                current_task.stage = "rejudging_template_evidences"
                current_task.stage_message = (
                    f"正在重新裁决 {index}/{len(results)}："
                    f"{item.citing_paper_title[:120]}"
                )
                self.db.commit()
            payload = self._load_json(result.parsed_result_json)
            payload = self._adjudicate_direct_evidences(
                item=item,
                provider=provider,
                payload=payload,
                active_templates=active_templates,
            )
            payload = self._apply_active_templates_to_direct_payload(
                item=item,
                payload=payload,
                active_templates=active_templates,
            )
            payload["rejudge_version"] = "template_adjudication.v1"
            payload["rejudged_at"] = datetime.utcnow().isoformat()
            evidence_counts = self._direct_evidence_counts(payload)
            payload.setdefault("diagnostics", {}).update(evidence_counts)
            result.parsed_result_json = json.dumps(payload, ensure_ascii=False)
            self.db.commit()
            TemplateDirectPersistenceService(self.db).persist(
                result.id,
                reconcile=True,
            )
            counts["evidence_count"] += evidence_counts[
                "parsed_evidence_count"
            ]
            counts["include_count"] += evidence_counts[
                "include_evidence_count"
            ]
            counts["review_count"] += evidence_counts[
                "review_evidence_count"
            ]
            counts["exclude_count"] += evidence_counts[
                "exclude_evidence_count"
            ]
            if task is not None:
                current_task = self.db.get(type(task), task.id)
                current_task.progress_current = index
                self.db.commit()
        return counts

    def _list_target_items(
        self,
        session_id: int,
        queue_item_ids: Optional[List[int]],
    ) -> List[DeepAnalysisQueueItem]:
        statement = select(DeepAnalysisQueueItem).where(
            DeepAnalysisQueueItem.scholar_session_id == session_id
        )
        if queue_item_ids:
            statement = statement.where(DeepAnalysisQueueItem.id.in_(queue_item_ids))
        statement = statement.order_by(DeepAnalysisQueueItem.priority_score.desc(), DeepAnalysisQueueItem.id.asc())
        return list(self.db.scalars(statement))

    def _count_fulltext_results(self, session_id: int) -> int:
        statement = select(FulltextAnalysisResult).where(
            FulltextAnalysisResult.scholar_session_id == session_id
        )
        return len(list(self.db.scalars(statement)))

    def _count_strong_evidence(self, session_id: int) -> int:
        statement = select(StrongEvidence).where(
            StrongEvidence.scholar_session_id == session_id
        )
        return len(list(self.db.scalars(statement)))

    def _persist_failed_fulltext_result(
        self,
        *,
        item: DeepAnalysisQueueItem,
        provider,
        analysis_scope: str,
        fulltext_chars: int,
        error_message: str,
        diagnostic_payload: Dict[str, str],
        prompt_text: str = "",
        task_id: Optional[int] = None,
    ) -> FulltextAnalysisResult:
        result = FulltextAnalysisResult(
            scholar_session_id=item.scholar_session_id,
            queue_item_id=item.id,
            citation_edge_id=item.citation_edge_id,
            analysis_scope=analysis_scope,
            status="failed",
            llm_provider=getattr(provider, "provider_name", settings.llm_provider),
            llm_model=settings.llm_model,
            prompt_version="phase13.v1",
            candidate_spans_json="{}",
            parsed_result_json=json.dumps(diagnostic_payload),
            error_message=error_message,
        )
        self.db.add(result)
        self.db.flush()
        candidate_payload = {
            "mode": analysis_scope,
            "fulltext_chars": fulltext_chars,
            "max_chars": settings.fulltext_direct_max_chars,
            "llm_findings_count": 0,
            "generated_strong_evidence_count": 0,
            "filtered_findings_count": 0,
            "filter_reason_distribution": {},
            "finding_diagnostics": [],
            "prompt_debug_enabled": bool(
                getattr(settings, "debug_save_llm_prompts", False)
            ),
            "prompt_chars": len(prompt_text or ""),
            "raw_response_chars": len(diagnostic_payload.get("raw_output_preview") or ""),
        }
        candidate_payload.update(
            self._maybe_save_llm_debug_files(
                prompt_text=prompt_text,
                raw_response_text=str(diagnostic_payload.get("raw_output_preview") or ""),
                normalized_response=diagnostic_payload,
                fulltext_result=result,
                analysis_scope=analysis_scope,
                task_id=task_id,
                provider=provider,
            )
        )
        result.candidate_spans_json = json.dumps(candidate_payload, ensure_ascii=False)
        self.db.commit()
        self.db.refresh(result)
        return result

    def _repair_fulltext_direct_response(
        self,
        *,
        raw_output: str,
        full_text: str,
        cited_paper_title: str,
    ) -> Optional[CitationAnalysisResponse]:
        try:
            payload = parse_llm_json_payload(raw_output)
        except Exception:
            return None
        findings = payload.get("findings") if isinstance(payload, dict) else None
        if not isinstance(findings, list):
            return None

        repaired_findings = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            repaired = self._repair_fulltext_direct_finding(
                finding=finding,
                full_text=full_text,
                cited_paper_title=cited_paper_title,
            )
            if repaired is not None:
                repaired_findings.append(repaired)

        try:
            return CitationAnalysisResponse.model_validate({"findings": repaired_findings})
        except ValidationError:
            return CitationAnalysisResponse.model_validate({"findings": []})

    def _repair_fulltext_direct_with_provider(
        self,
        *,
        provider,
        request: LlmCitationAnalysisRequest,
        raw_output: str,
        cited_paper_title: str,
    ) -> Optional[CitationAnalysisResponse]:
        if not raw_output:
            return None
        repair_prompt = build_fulltext_direct_repair_prompt(
            model_output=raw_output,
            cited_paper_title=cited_paper_title,
        )
        repair_request = request.model_copy(
            update={
                "analysis_scope": "fulltext_direct_repair",
                "prompt_text": repair_prompt,
                "full_text": None,
                "candidate_spans": [],
            }
        )
        try:
            return provider.analyze_citation(repair_request)
        except ProviderException:
            return None

    def _repair_fulltext_direct_finding(
        self,
        *,
        finding: Dict[str, object],
        full_text: str,
        cited_paper_title: str,
    ) -> Optional[Dict[str, object]]:
        if finding.get("keep") is False:
            return None

        citation_text = str(finding.get("citation_text") or "").strip()
        if not citation_text:
            return None
        if self._should_skip_fulltext_direct_finding(
            citation_text=citation_text,
            mention_type=str(finding.get("mention_type") or ""),
            full_text=full_text,
            cited_paper_title=cited_paper_title,
        ):
            return None

        repaired = dict(finding)
        repaired["citation_text"] = citation_text
        if not repaired.get("evidence_type"):
            inferred_type = self._infer_supported_evidence_type(citation_text)
            if inferred_type is None:
                return None
            repaired["evidence_type"] = inferred_type
        if not repaired.get("stance"):
            repaired["stance"] = self._infer_supported_stance(
                citation_text,
                str(repaired["evidence_type"]),
            )
        if not repaired.get("mention_type"):
            repaired["mention_type"] = self._infer_supported_mention_type(
                citation_text,
                str(repaired["evidence_type"]),
                cited_paper_title,
            )
        if not repaired.get("reasoning"):
            repaired["reasoning"] = (
                "The quote explicitly discusses the cited paper in the main body, "
                "and the classification is supported by the quoted wording."
            )
        if "highlight_keywords" in repaired and "keywords" not in repaired:
            repaired["keywords"] = repaired["highlight_keywords"]
        return repaired

    def _should_skip_fulltext_direct_finding(
        self,
        *,
        citation_text: str,
        mention_type: str,
        full_text: str,
        cited_paper_title: str,
    ) -> bool:
        if mention_type == "reference_only":
            return True
        if self._looks_like_reference_entry(citation_text, full_text, cited_paper_title):
            return True
        if not self._is_attributed_body_quote(citation_text, full_text, cited_paper_title):
            return True
        return False

    def _fulltext_direct_filter_reason(
        self,
        *,
        citation_text: str,
        mention_type: str,
        full_text: str,
        cited_paper_title: str,
        evidence_type: str,
        stance: str,
        reference_anchor,
        citation_text_contains_target_marker: bool,
        citation_text_in_target_context: bool,
    ) -> Optional[str]:
        if mention_type == "reference_only":
            return "reference_only"
        if self._looks_like_reference_entry(citation_text, full_text, cited_paper_title):
            return "reference_entry"
        if evidence_type == "background" and stance == "neutral":
            if (
                (citation_text_contains_target_marker or citation_text_in_target_context)
                and self._background_anchor_upgrade_type(
                    citation_text=citation_text,
                    reasoning="",
                )
            ):
                return None
            return "background_neutral"
        if citation_text_contains_target_marker or citation_text_in_target_context:
            return None
        if not self._is_attributed_body_quote(citation_text, full_text, cited_paper_title):
            return "no_body_anchor"
        return None

    def _looks_like_reference_entry(
        self,
        citation_text: str,
        full_text: str,
        cited_paper_title: str,
    ) -> bool:
        normalized_quote = self._normalize_text(citation_text)
        if not normalized_quote:
            return True
        quote_index = self._find_normalized_index(full_text, citation_text)
        reference_start = self._reference_section_start(full_text)
        if reference_start is not None and quote_index is not None and quote_index >= reference_start:
            return True

        reference_markers = ("proc.", " pp.", " vol.", " doi", " arxiv", " conf.", " int. conf.")
        has_reference_marker = any(marker in normalized_quote for marker in reference_markers)
        has_year = re.search(r"\b(19|20)\d{2}\b", normalized_quote) is not None
        has_author_initials = re.search(r"\b[a-z]\.\s*[a-z\-]+", normalized_quote) is not None
        title_overlap = self._title_overlap(normalized_quote, self._normalize_text(cited_paper_title))
        return bool(has_reference_marker and has_year and (has_author_initials or title_overlap >= 0.6))

    def _is_attributed_body_quote(
        self,
        citation_text: str,
        full_text: str,
        cited_paper_title: str,
    ) -> bool:
        quote_index = self._find_normalized_index(full_text, citation_text)
        reference_start = self._reference_section_start(full_text)
        if reference_start is not None and quote_index is not None and quote_index >= reference_start:
            return False

        normalized_title = self._normalize_text(cited_paper_title)
        normalized_quote = self._normalize_text(citation_text)
        if normalized_title and normalized_title in normalized_quote:
            return True
        if quote_index is None:
            return False
        window_start = max(0, quote_index - 600)
        window_end = min(len(full_text), quote_index + len(citation_text) + 600)
        normalized_window = self._normalize_text(full_text[window_start:window_end])
        return bool(normalized_title and normalized_title in normalized_window)

    def _infer_supported_evidence_type(self, citation_text: str) -> Optional[str]:
        normalized = self._normalize_text(citation_text)
        if any(term in normalized for term in ("first", "seminal", "pioneer", "pioneering")):
            return "first_or_seminal_claim"
        if any(term in normalized for term in ("detailed comparison", "compare", "compared", "comparison")):
            return "detailed_comparison"
        if any(term in normalized for term in ("baseline", "benchmark")):
            return "baseline_or_benchmark"
        if any(term in normalized for term in ("method foundation", "methodological foundation", "builds on", "based on")):
            return "method_foundation"
        if any(term in normalized for term in ("theoretical foundation", "theory", "theoretical")):
            return "theoretical_foundation"
        if any(term in normalized for term in ("extend", "extension", "application")):
            return "application_extension"
        if any(term in normalized for term in ("positive", "effective", "accurate", "robust", "high precision", "important")):
            return "positive_evaluation"
        if any(term in normalized for term in ("limitation", "negative", "fail", "weakness")):
            return "limitation_or_negative"
        return None

    def _infer_supported_stance(self, citation_text: str, evidence_type: str) -> str:
        normalized = self._normalize_text(citation_text)
        if evidence_type == "limitation_or_negative" or any(
            term in normalized for term in ("limitation", "negative", "fail", "weakness")
        ):
            return "negative"
        if evidence_type in {"positive_evaluation", "method_foundation", "first_or_seminal_claim"}:
            return "positive"
        return "neutral"

    def _infer_supported_mention_type(
        self,
        citation_text: str,
        evidence_type: str,
        cited_paper_title: str,
    ) -> str:
        normalized_quote = self._normalize_text(citation_text)
        if self._normalize_text(cited_paper_title) in normalized_quote:
            return "explicit_target"
        if evidence_type in {"detailed_comparison", "baseline_or_benchmark"}:
            return "comparison"
        if evidence_type in {"method_foundation", "theoretical_foundation"}:
            return "method_use"
        return "other"

    def _reference_section_start(self, text: str) -> Optional[int]:
        match = re.search(r"(?im)^\s*(references|bibliography)\s*$", text or "")
        return match.start() if match else None

    def _find_normalized_index(self, haystack: str, needle: str) -> Optional[int]:
        if not haystack or not needle:
            return None
        direct = haystack.find(needle)
        if direct >= 0:
            return direct
        normalized_haystack = self._normalize_text(haystack)
        normalized_needle = self._normalize_text(needle)
        index = normalized_haystack.find(normalized_needle)
        return index if index >= 0 else None

    def _title_overlap(self, quote: str, title: str) -> float:
        title_terms = {
            term
            for term in re.findall(r"[a-z0-9]+", title)
            if len(term) >= 4
        }
        if not title_terms:
            return 0.0
        quote_terms = set(re.findall(r"[a-z0-9]+", quote))
        return len(title_terms & quote_terms) / len(title_terms)

    def _normalize_text(self, value: str) -> str:
        ascii_text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
        return " ".join(ascii_text.lower().split())

    def _span_index(self, citation_text: str, candidate_spans: Iterable[str]) -> Optional[int]:
        for index, span_text in enumerate(candidate_spans):
            if span_text == citation_text:
                return index
        return None

    def _normalize_analysis_scope(self, analysis_scope: str) -> str:
        if analysis_scope in {"candidate_spans", "scholar_queue", "", None}:
            return "candidate_spans"
        if analysis_scope == "fulltext_direct":
            return "fulltext_direct"
        if analysis_scope == "fulltext_anchor_direct":
            return "fulltext_anchor_direct"
        if analysis_scope == "fulltext_template_direct":
            return "fulltext_template_direct"
        raise ValueError(f"Unsupported analysis_scope: {analysis_scope}")

    def _target_aliases(self, cited_title: str, cited_authors: List[str]) -> List[str]:
        aliases = [cited_title]
        title_words = [
            word.strip(" :;,.()[]{}")
            for word in re.split(r"\s+", cited_title or "")
            if len(word.strip(" :;,.()[]{}")) >= 5
        ]
        if title_words:
            aliases.append(" ".join(title_words[: min(6, len(title_words))]))
        if ":" in (cited_title or ""):
            aliases.append(cited_title.split(":", 1)[0].strip())
        if cited_authors:
            family = cited_authors[0].split()[-1]
            aliases.extend([f"{family} et al.", f"{family} et al. 2022"])
        seen = set()
        result = []
        for alias in aliases:
            cleaned = (alias or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    def _load_authors(self, publication: Optional[Publication]) -> List[str]:
        if publication is None or not publication.authors_json:
            return []
        try:
            parsed = json.loads(publication.authors_json)
        except json.JSONDecodeError:
            return []
        return [str(author) for author in parsed] if isinstance(parsed, list) else []

    def _load_json(self, value: Optional[str]):
        if not value:
            return {}
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}

    def _diagnostic_count(self, parsed_payload, candidate_payload, key: str) -> int:
        value = self._diagnostic_value(candidate_payload, key)
        if value is None and isinstance(parsed_payload, dict):
            value = parsed_payload.get("diagnostics", {}).get(key)
        return int(value or 0)

    def _direct_evidence_counts(self, parsed_payload) -> Dict[str, int]:
        evidences = (
            parsed_payload.get("evidences", [])
            if isinstance(parsed_payload, dict)
            else []
        )
        if not isinstance(evidences, list):
            evidences = []
        valid_evidences = [
            evidence for evidence in evidences if isinstance(evidence, dict)
        ]
        include_count = sum(
            1
            for evidence in valid_evidences
            if self._final_direct_recommendation(evidence) == "include"
        )
        aligned_count = sum(
            1
            for evidence in valid_evidences
            if self._direct_reference_status(evidence) == "matched"
        )
        unresolved_count = sum(
            1
            for evidence in valid_evidences
            if self._direct_reference_status(evidence) in {"", "unresolved", "unknown"}
        )
        eligible_count = sum(
            1 for evidence in valid_evidences if self._is_template_eligible_candidate(evidence)
        )
        matched_count = sum(
            1
            for evidence in valid_evidences
            if evidence.get("template_satisfied") is True
            and bool(evidence.get("matched_template_ids"))
        )
        review_count = sum(
            1
            for evidence in valid_evidences
            if self._final_direct_recommendation(evidence) == "review"
        )
        exclude_count = sum(
            1
            for evidence in valid_evidences
            if self._final_direct_recommendation(evidence) == "exclude"
        )
        verified_count = sum(
            1
            for evidence in valid_evidences
            if evidence.get("grounding_status") == "verified"
        )
        verified_substantive_count = sum(
            1
            for evidence in valid_evidences
            if evidence.get("grounding_status") == "verified"
            and evidence.get("evidence_strength") in {"strong", "medium"}
            and evidence.get("template_relation") != "unmatched"
        )
        ordinary_false_positive_count = sum(
            1
            for evidence in valid_evidences
            if str(evidence.get("claim_type") or "") == "ordinary_reference"
            and self._final_direct_recommendation(evidence) == "include"
        )
        mismatch_false_positive_count = sum(
            1
            for evidence in valid_evidences
            if evidence.get("grounding_status")
            in {"mismatch", "attribution_conflict"}
            and self._final_direct_recommendation(evidence) == "include"
        )
        return {
            "parsed_evidence_count": len(valid_evidences),
            "include_evidence_count": include_count,
            "review_evidence_count": review_count,
            "exclude_evidence_count": exclude_count,
            "generated_strong_evidence_count": include_count,
            "extracted_candidate_count": len(valid_evidences),
            "aligned_candidate_count": aligned_count,
            "unresolved_candidate_count": unresolved_count,
            "template_eligible_candidate_count": eligible_count,
            "template_matched_candidate_count": matched_count,
            "verified_evidence_count": verified_count,
            "verified_substantive_evidence_count": verified_substantive_count,
            "ordinary_reference_false_positive_count": (
                ordinary_false_positive_count
            ),
            "reference_mismatch_false_positive_count": (
                mismatch_false_positive_count
            ),
            "final_include_count": include_count,
            "final_review_count": review_count,
            "final_exclude_count": exclude_count,
        }

    def _final_direct_recommendation(self, evidence: dict) -> str:
        return str(
            evidence.get("final_recommendation")
            or evidence.get("recommendation")
            or ""
        )

    def _direct_reference_status(self, evidence: dict) -> str:
        return str(
            evidence.get("reference_alignment_status")
            or evidence.get("reference_match_status")
            or ""
        ).lower()

    def _is_template_eligible_candidate(self, evidence: dict) -> bool:
        if self._direct_reference_status(evidence) != "matched":
            return False
        if evidence.get("reference_attribution_conflict"):
            return False
        if str(evidence.get("target_anchor_status") or "") == "missing":
            return False
        reason_codes = set(direct_evidence_failure_reason_codes(evidence))
        return not bool(
            reason_codes
            & {
                "reference_mismatch",
                "target_marker_missing",
                "reference_only",
            }
        )

    def _direct_persistence_counts(
        self,
        result: FulltextAnalysisResult,
    ) -> Dict[str, int]:
        candidate_payload = self._load_json(result.candidate_spans_json)
        persisted_evidence_count = (
            self.db.query(StrongEvidence)
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )
        from app.models import HighlightCard

        persisted_card_count = (
            self.db.query(HighlightCard)
            .join(
                StrongEvidence,
                HighlightCard.strong_evidence_id == StrongEvidence.id,
            )
            .filter(StrongEvidence.fulltext_result_id == result.id)
            .count()
        )
        return {
            "strong_evidence_count": persisted_evidence_count,
            "persisted_strong_evidence_count": persisted_evidence_count,
            "generated_highlight_card_count": int(
                candidate_payload.get("generated_highlight_card_count")
                or persisted_evidence_count
            ),
            "persisted_highlight_card_count": persisted_card_count,
            "strong_evidence_persistence_failed_count": int(
                candidate_payload.get("strong_evidence_persistence_failed_count")
                or 0
            ),
            "highlight_card_persistence_failed_count": int(
                candidate_payload.get("highlight_card_persistence_failed_count")
                or 0
            ),
        }

    def _diagnostic_value(self, candidate_payload, key: str, default=None):
        if isinstance(candidate_payload, dict):
            return candidate_payload.get(key, default)
        return default

    def _candidate_spans_count(self, candidate_payload) -> int:
        if isinstance(candidate_payload, dict):
            spans = candidate_payload.get("spans")
            if isinstance(spans, list):
                return len(spans)
            return int(candidate_payload.get("candidate_spans_count") or 0)
        if isinstance(candidate_payload, list):
            return len(candidate_payload)
        return 0

    def _debug_file_preview(self, basename: str, limit: int = 3000, result_id: Optional[int] = None) -> str:
        path = self._debug_file_path(basename, result_id=result_id)
        if path is None or not path.exists():
            return ""
        return self._redact_sensitive(path.read_text(encoding="utf-8")[:limit])

    def _debug_file_path(self, basename: str, *, result_id: Optional[int] = None) -> Optional[Path]:
        safe_name = Path(basename or "").name
        if not safe_name:
            return None
        if result_id is not None:
            candidate = self._debug_llm_dir() / f"result_{result_id}" / safe_name
            return candidate if candidate.is_file() else None
        for path in sorted(self._debug_llm_dir().glob(f"result_*/{safe_name}"), reverse=True):
            if path.is_file():
                return path
        return None

    def read_debug_artifact(
        self,
        *,
        session_id: int,
        result_id: int,
        kind: str,
    ) -> Dict[str, object]:
        result = self.db.get(FulltextAnalysisResult, result_id)
        if result is None or result.scholar_session_id != session_id:
            raise ValueError(f"FulltextAnalysisResult {result_id} was not found")
        payload = self._load_json(result.candidate_spans_json)
        name_map = {
            "prompt": self._diagnostic_value(payload, "prompt_debug_file", ""),
            "raw_response": self._diagnostic_value(payload, "raw_response_debug_file", ""),
            "normalized_response": self._diagnostic_value(payload, "normalized_response_debug_file", ""),
            "metadata": self._diagnostic_value(payload, "metadata_debug_file", ""),
        }
        basename = name_map.get(kind, "")
        path = self._debug_file_path(basename, result_id=result.id)
        if not basename or path is None or not path.exists():
            raise ValueError(f"Debug artifact {kind} is not available")
        content = path.read_text(encoding="utf-8")
        return {
            "basename": path.name,
            "content": self._redact_sensitive(content),
            "media_type": "application/json" if path.suffix == ".json" else "text/plain",
        }

    def _truncate(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[:limit] + "..."

    def _preview_findings(self, findings) -> str:
        if not isinstance(findings, list):
            return ""
        preview = json.dumps(findings[:3], ensure_ascii=False)
        return self._redact_sensitive(preview[:1200])

    def _redact_sensitive(self, value: str) -> str:
        redacted = str(value or "")
        redacted = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "[redacted-api-key]", redacted)
        redacted = re.sub(
            r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*['\"]?[^,'\"\s}]+",
            r"\1=[redacted]",
            redacted,
        )
        return redacted


def get_scholar_fulltext_service(db: Session = Depends(get_db)) -> ScholarFulltextService:
    return ScholarFulltextService(db)

"""Core Phase 1 SQLAlchemy models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_kind: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[int] = mapped_column(Integer)
    task_type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stage_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PaperAnalysisSession(Base):
    __tablename__ = "paper_analysis_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_text: Mapped[str] = mapped_column(Text)
    query_kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="created")
    provider_total_citation_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    displayed_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    openalex_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    semantic_scholar_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scopus_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dblp_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    authors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TargetPaper(Base):
    __tablename__ = "target_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_session_id: Mapped[int] = mapped_column(ForeignKey("paper_analysis_sessions.id"))
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    raw_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by_provider: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class CitingPaper(Base):
    __tablename__ = "citing_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_session_id: Mapped[int] = mapped_column(ForeignKey("paper_analysis_sessions.id"))
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    local_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    analysis_status: Mapped[str] = mapped_column(String(32), default="pending")
    pdf_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pdf_assets.id"), nullable=True)


class PdfAsset(Base):
    __tablename__ = "pdf_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    storage_path: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    extract_status: Mapped[str] = mapped_column(String(32), default="pending")
    extracted_text_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PdfAssetPublicationLink(Base):
    __tablename__ = "pdf_asset_publication_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pdf_asset_id: Mapped[int] = mapped_column(ForeignKey("pdf_assets.id"))
    publication_id: Mapped[Optional[int]] = mapped_column(ForeignKey("publications.id"), nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    openalex_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    normalized_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_method: Mapped[str] = mapped_column(String(128))
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class FulltextAnalysisResult(Base):
    __tablename__ = "fulltext_analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paper_analysis_sessions.id"),
        nullable=True,
    )
    scholar_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scholar_analysis_sessions.id"),
        nullable=True,
    )
    citing_paper_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("citing_papers.id"),
        nullable=True,
    )
    queue_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deep_analysis_queue_items.id"),
        nullable=True,
    )
    citation_edge_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("citation_edges.id"),
        nullable=True,
    )
    analysis_scope: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    llm_provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    candidate_spans_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StrongEvidence(Base):
    __tablename__ = "strong_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fulltext_result_id: Mapped[int] = mapped_column(ForeignKey("fulltext_analysis_results.id"))
    scholar_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scholar_analysis_sessions.id"),
        nullable=True,
    )
    queue_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deep_analysis_queue_items.id"),
        nullable=True,
    )
    citation_edge_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("citation_edges.id"),
        nullable=True,
    )
    aspect: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stance: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mention_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    citation_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlighted_text_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlight_keywords_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    span_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    anchor_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_self_citation: Mapped[bool] = mapped_column(Boolean, default=False)
    third_party_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    review_status: Mapped[str] = mapped_column(String(64), default="unreviewed")
    user_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_strength: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    matched_template_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_satisfied: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    template_failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class HighlightCard(Base):
    __tablename__ = "highlight_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scholar_session_id: Mapped[int] = mapped_column(ForeignKey("scholar_analysis_sessions.id"))
    strong_evidence_id: Mapped[int] = mapped_column(ForeignKey("strong_evidences.id"))
    card_type: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text)
    subtitle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    narrative_zh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    narrative_en: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_markdown: Mapped[str] = mapped_column(Text)
    evidence_quote: Mapped[str] = mapped_column(Text)
    highlighted_quote_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_citing_paper_title: Mapped[str] = mapped_column(Text)
    source_cited_paper_title: Mapped[str] = mapped_column(Text)
    citing_authors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notable_author_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notable_author_affiliation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notable_author_role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fellow_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    venue_tier: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    aspect: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stance: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_strength: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_evidence_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    review_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    user_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    include_in_report: Mapped[bool] = mapped_column(Boolean, default=True)
    matched_template_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_template_names: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_satisfied: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    template_failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class NotableAuthor(Base):
    __tablename__ = "notable_authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    affiliation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fellow_status: Mapped[str] = mapped_column(String(64), default="unknown")
    homepage: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_manual_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CitationAuthorAnnotation(Base):
    __tablename__ = "citation_author_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scholar_session_id: Mapped[int] = mapped_column(ForeignKey("scholar_analysis_sessions.id"))
    queue_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deep_analysis_queue_items.id"),
        nullable=True,
    )
    citation_edge_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("citation_edges.id"),
        nullable=True,
    )
    citing_publication_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("publications.id"),
        nullable=True,
    )
    notable_author_id: Mapped[int] = mapped_column(ForeignKey("notable_authors.id"))
    citing_author_name: Mapped[str] = mapped_column(Text)
    citing_author_affiliation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    honor_category: Mapped[str] = mapped_column(Text)
    citing_paper_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_citing_paper_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_citing_venue_short: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_citing_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parsed_citing_pub_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    my_cited_paper_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_citing_paper_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_cited_paper_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_method: Mapped[str] = mapped_column(String(64), default="unmatched")
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_status: Mapped[str] = mapped_column(String(32), default="unmatched")
    unmatched_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_important: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AnalysisTemplate(Base):
    __tablename__ = "analysis_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_kind: Mapped[str] = mapped_column(String(64), default="scholar_analysis")
    session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_type: Mapped[str] = mapped_column(String(128))
    natural_language_goal: Mapped[str] = mapped_column(Text)
    target_aspects_json: Mapped[str] = mapped_column(Text, default="[]")
    positive_keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    negative_keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    required_evidence_patterns_json: Mapped[str] = mapped_column(Text, default="[]")
    prompt_fragment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scoring_rules_json: Mapped[str] = mapped_column(Text, default="{}")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TemplateMatch(Base):
    __tablename__ = "template_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("analysis_templates.id"))
    strong_evidence_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strong_evidences.id"),
        nullable=True,
    )
    queue_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deep_analysis_queue_items.id"),
        nullable=True,
    )
    matched_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    matched_reason: Mapped[str] = mapped_column(Text)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EvidenceReview(Base):
    __tablename__ = "evidence_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strong_evidence_id: Mapped[int] = mapped_column(ForeignKey("strong_evidences.id"))
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    user_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    corrected_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScholarAnalysisSession(Base):
    __tablename__ = "scholar_analysis_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    dblp_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    openalex_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scopus_author_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created")
    publication_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_edge_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScholarPublication(Base):
    __tablename__ = "scholar_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scholar_session_id: Mapped[int] = mapped_column(ForeignKey("scholar_analysis_sessions.id"))
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    local_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    selected_for_expansion: Mapped[bool] = mapped_column(Boolean, default=False)
    pdf_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pdf_assets.id"), nullable=True)


class CitationEdge(Base):
    __tablename__ = "citation_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scholar_session_id: Mapped[int] = mapped_column(ForeignKey("scholar_analysis_sessions.id"))
    cited_publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    citing_publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    provider_name: Mapped[str] = mapped_column(String(64))
    self_citation_status: Mapped[str] = mapped_column(String(64), default="unknown")
    third_party_status: Mapped[str] = mapped_column(String(64), default="third_party")
    edge_meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PdfLibraryIndex(Base):
    __tablename__ = "pdf_library_indexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_path: Mapped[str] = mapped_column(Text)
    source_dirs_json: Mapped[str] = mapped_column(Text)
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PdfLibraryEntry(Base):
    __tablename__ = "pdf_library_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_id: Mapped[int] = mapped_column(ForeignKey("pdf_library_indexes.id"))
    file_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    detected_doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detected_arxiv_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    normalized_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title_candidates_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PdfInboxEntry(Base):
    __tablename__ = "pdf_inbox_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    pdf_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pdf_assets.id"), nullable=True)
    detected_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    match_status: Mapped[str] = mapped_column(String(64), default="unmatched")
    match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_queue_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("deep_analysis_queue_items.id"), nullable=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ExternalCitationImportBatch(Base):
    __tablename__ = "external_citation_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_kind: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[int] = mapped_column(Integer)
    source_name: Mapped[str] = mapped_column(String(128))
    filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_existing_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExternalCitationImportRow(Base):
    __tablename__ = "external_citation_import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("external_citation_import_batches.id"))
    row_index: Mapped[int] = mapped_column(Integer)
    raw_row_json: Mapped[str] = mapped_column(Text)
    parsed_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    parsed_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parsed_venue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_status: Mapped[str] = mapped_column(String(64))
    match_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    citation_edge_id: Mapped[Optional[int]] = mapped_column(ForeignKey("citation_edges.id"), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DeepAnalysisQueueItem(Base):
    __tablename__ = "deep_analysis_queue_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scholar_session_id: Mapped[int] = mapped_column(ForeignKey("scholar_analysis_sessions.id"))
    citation_edge_id: Mapped[int] = mapped_column(ForeignKey("citation_edges.id"))
    cited_publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    citing_publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"))
    queue_status: Mapped[str] = mapped_column(String(32), default="pending")
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    third_party_status: Mapped[str] = mapped_column(String(64), default="ambiguous")
    self_citation_status: Mapped[str] = mapped_column(String(64), default="unknown")
    pdf_readiness_status: Mapped[str] = mapped_column(String(64), default="need_pdf")
    pdf_discovery_status: Mapped[str] = mapped_column(String(64), default="not_started")
    pdf_access_status: Mapped[str] = mapped_column(String(64), default="manual_download_needed")
    pdf_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pdf_source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    publisher_landing_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doi_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    openalex_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_scholar_query_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    publisher_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    requires_login_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pdf_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pdf_assets.id"), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    venue_tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    citing_paper_title: Mapped[str] = mapped_column(Text)
    cited_paper_title: Mapped[str] = mapped_column(Text)
    citing_authors_json: Mapped[str] = mapped_column(Text, default="[]")
    cited_authors_json: Mapped[str] = mapped_column(Text, default="[]")
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    provider_name: Mapped[str] = mapped_column(String(64))
    user_review_status: Mapped[str] = mapped_column(String(64), default="unreviewed")
    user_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

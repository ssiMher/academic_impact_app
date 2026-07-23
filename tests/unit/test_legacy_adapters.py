import json
from pathlib import Path

import pytest

from app.legacy.adapters.candidate_spans_adapter import (
    LegacyFulltextPage,
    find_legacy_candidate_spans,
)
from app.legacy.adapters.dblp_normalize_adapter import normalize_dblp_id
from app.legacy.adapters.evidence_normalize_adapter import (
    normalize_evidence_label,
    normalize_highlight_keywords,
    normalize_legacy_finding,
)
from app.legacy.adapters.llm_json_parser_adapter import parse_legacy_llm_json
from app.legacy.adapters.local_pdf_match_adapter import match_local_pdf
from app.legacy.adapters.pdf_extract_adapter import (
    classify_pdf_extract_error,
    extract_pdf_text_with_legacy_adapter,
)
from tests.unit.test_pdf_service import build_minimal_pdf


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "legacy"


def load_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_llm_json_parser_extracts_fenced_json_regression_fixture():
    result = parse_legacy_llm_json(load_fixture("llm_response_cases.json")["fenced_json_with_thinking"])

    assert result.findings[0].evidence_type == "method_foundation"
    assert result.findings[0].citation_text == "LoRA is a method foundation."


def test_llm_json_parser_extracts_embedded_json_regression_fixture():
    result = parse_legacy_llm_json(load_fixture("llm_response_cases.json")["embedded_json"])

    assert result.findings[0].evidence_type == "baseline_or_benchmark"
    assert result.findings[0].stance == "neutral"


def test_candidate_spans_adapter_finds_body_span_before_references():
    fixture = load_fixture("candidate_span_case.json")
    result = find_legacy_candidate_spans(
        pages=[
            LegacyFulltextPage(page=page["page"], text=page["text"])
            for page in fixture["pages"]
        ],
        target_title=fixture["target_title"],
        target_doi=fixture["target_doi"],
    )

    assert result.ok is True
    assert result.reference_start_page == fixture["expected"]["reference_start_page"]
    assert result.spans
    assert result.spans[0].page == fixture["expected"]["first_span_page"]
    assert fixture["expected"]["first_span_contains"] in result.spans[0].text


def test_pdf_extract_adapter_extracts_minimal_pdf(tmp_path):
    fixture = load_fixture("pdf_extract_case.json")
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(build_minimal_pdf(fixture["pdf_text"]))

    result = extract_pdf_text_with_legacy_adapter(pdf_path)

    assert result.ok is True
    assert result.page_count == fixture["expected"]["page_count"]
    assert fixture["expected"]["text_contains"] in result.text


def test_pdf_extract_adapter_classifies_corrupted_pdf_error():
    result = classify_pdf_extract_error(RuntimeError("Stream has ended unexpectedly"))

    assert result.error_type == "pdf_corrupted_or_malformed"
    assert result.error_stage == "extract_text_failed"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("conf/vldb/Smith2024", "conf/vldb/Smith2024"),
        ("https://dblp.org/rec/conf/vldb/Smith2024.html", "conf/vldb/Smith2024"),
        ("dblp: journals/tods/Chen2025", "journals/tods/Chen2025"),
        ("DBLP:journals/tods/Chen2025/", "journals/tods/Chen2025"),
    ],
)
def test_dblp_normalize_adapter(raw, expected):
    assert normalize_dblp_id(raw) == expected


def test_local_pdf_match_adapter_matches_title_doi_and_arxiv(tmp_path):
    title_match = tmp_path / "Low-Rank Adaptation of Large Language Models.pdf"
    doi_match = tmp_path / "10.1234_lora.pdf"
    arxiv_match = tmp_path / "2106.09685.pdf"
    for path in (title_match, doi_match, arxiv_match):
        path.write_bytes(b"%PDF-1.4\n")

    assert match_local_pdf(search_dir=tmp_path, title="Low Rank Adaptation of Large Language Models").path == title_match
    assert match_local_pdf(search_dir=tmp_path, doi="10.1234/lora").path == doi_match
    assert match_local_pdf(search_dir=tmp_path, arxiv_id="arXiv:2106.09685v2").path == arxiv_match


def test_evidence_normalize_adapter_maps_labels_and_keywords():
    fixture = load_fixture("evidence_normalization_case.json")
    normalized = normalize_legacy_finding(fixture["legacy_finding"])

    assert normalized.aspect == fixture["expected"]["aspect"]
    assert normalized.stance == fixture["expected"]["stance"]
    assert normalized.mention_type == fixture["expected"]["mention_type"]
    assert normalized.confidence == fixture["expected"]["confidence"]
    assert normalized.keep is fixture["expected"]["keep"]
    assert normalized.highlight_keywords == fixture["expected"]["highlight_keywords"]

    assert normalize_evidence_label("baseline") == "baseline_or_benchmark"
    assert normalize_evidence_label("method") == "method_foundation"
    assert normalize_highlight_keywords(
        citation_text="LoRA is a method foundation for this benchmark.",
        keywords=["method foundation", "missing", "LoRA", "lora"],
    ) == ["method foundation", "LoRA"]


def test_new_services_do_not_import_legacy_project_core_directly():
    service_files = (Path(__file__).resolve().parents[2] / "app" / "services").glob("*.py")
    forbidden = (
        "academic_impact_web",
        "impact_core",
        "scholar_core",
        "run_pipeline",
        "session.json",
    )

    for path in service_files:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path

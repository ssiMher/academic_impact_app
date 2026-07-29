import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.prompt_builder import (
    build_citation_analysis_prompt,
    build_fulltext_template_direct_prompt,
)
from app.analysis.template_matching import format_template_snapshots_for_prompt
from app.analysis.evidence_interpretation import interpret_evidence
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisTemplate,
    CitationEdge,
    DeepAnalysisQueueItem,
    FulltextAnalysisResult,
    Publication,
    ScholarAnalysisSession,
    StrongEvidence,
    TemplateMatch,
)
from app.repositories.pdf_repo import PdfRepository
from app.repositories.scholar_queue_repo import ScholarQueueRepository
from app.services.highlight_card_service import HighlightCardService
from app.services.pdf_library_service import PdfLibraryService
from app.services.scholar_fulltext_service import ScholarFulltextService
from app.services.scholar_queue_service import ScholarQueueService
from app.services.scholar_report_service import ScholarReportService
from app.services.template_service import TemplateService
from app.schemas.llm import CitationAnalysisResponse
from tests.test_scholar_evidence import (
    CapturingTemplateDirectProvider,
    seed_queue_item,
    set_model_template_decision,
)


class RecordingNoFindingsLlmProvider:
    provider_name = "recording-no-findings-fake-llm"

    def __init__(self):
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        return type(
            "NoFindingsResponse",
            (),
            {
                "findings": [],
                "model_dump_json": lambda self: json.dumps({"findings": []}),
            },
        )()


class RecordingFindingsLlmProvider:
    provider_name = "recording-template-findings-llm"

    def __init__(self, response):
        self.response = CitationAnalysisResponse.model_validate(response)
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        return self.response


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def client(db_session_factory):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def make_queue_service(db, tmp_path):
    return ScholarQueueService(
        repository=ScholarQueueRepository(db),
        pdf_library_service=PdfLibraryService(
            repository=PdfRepository(db),
            library_dirs=[],
            index_path=tmp_path / "pdf_index.json",
            max_scan_files=100,
            match_threshold=0.82,
        ),
    )


def seed_edge_for_template_queue(db, *, citing_title="Benchmark Baseline Evaluation"):
    session = ScholarAnalysisSession(
        display_name="Grace Hopper",
        status="expanded",
        publication_count=1,
        citation_edge_count=1,
    )
    cited = Publication(
        title="Cited Scholar Paper",
        year=2021,
        venue="Journal",
        authors_json=json.dumps(["Grace Hopper"]),
    )
    citing = Publication(
        title=citing_title,
        year=2025,
        venue="Science",
        authors_json=json.dumps(["Lin Chen"]),
    )
    db.add_all([session, cited, citing])
    db.flush()
    db.add(
        CitationEdge(
            scholar_session_id=session.id,
            cited_publication_id=cited.id,
            citing_publication_id=citing.id,
            provider_name="fake",
            self_citation_status="not_self_citation",
            third_party_status="third_party",
        )
    )
    db.commit()
    return session.id


def seed_evidence_for_templates(db, tmp_path):
    session_id, item_id = seed_queue_item(
        db,
        tmp_path,
        text="Cited Scholar Paper is used as a benchmark baseline.",
    )
    item = db.get(DeepAnalysisQueueItem, item_id)
    result = FulltextAnalysisResult(
        scholar_session_id=session_id,
        queue_item_id=item_id,
        citation_edge_id=item.citation_edge_id,
        analysis_scope="scholar_queue",
        status="succeeded",
        parsed_result_json=json.dumps({"findings": []}),
    )
    db.add(result)
    db.flush()
    evidence = StrongEvidence(
        fulltext_result_id=result.id,
        scholar_session_id=session_id,
        queue_item_id=item_id,
        citation_edge_id=item.citation_edge_id,
        aspect="method_foundation",
        stance="positive",
        mention_type="strong",
        citation_text="Cited Scholar Paper is used as a benchmark baseline.",
        highlighted_text_html="Cited Scholar Paper is used as a <mark>benchmark baseline</mark>.",
        highlight_keywords_json=json.dumps(["benchmark baseline"]),
        evidence_reason="Contains benchmark baseline wording.",
        evidence_strength="strong",
        score=0.9,
        third_party_status="third_party",
        review_status="accepted",
    )
    db.add(evidence)
    db.commit()
    return session_id, evidence.id


def test_list_builtin_templates(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        templates = TemplateService(db).list_builtin_templates()
        positive = next(
            template
            for template in templates
            if template.template_type == "positive_evaluation"
        )

    assert len(templates) >= 11
    assert any(template.template_type == "baseline_or_benchmark" for template in templates)
    assert any("开创" in template.description for template in templates)
    assert "Explicit praise is not required" in positive.natural_language_goal
    assert "method, mechanism, capability, effect, or contribution" in (
        positive.natural_language_goal
    )


def test_legacy_positive_template_clone_is_upgraded_without_overwriting_user_goal(
    db_session_factory,
):
    with Session(db_session_factory.kw["bind"]) as db:
        legacy = AnalysisTemplate(
            session_kind="scholar_analysis",
            session_id=29,
            name="positive_evaluation",
            description="正向评价",
            template_type="positive_evaluation",
            natural_language_goal="Find positive evaluations of the target paper.",
            target_aspects_json='["positive_evaluation"]',
            positive_keywords_json="[]",
            negative_keywords_json="[]",
            required_evidence_patterns_json="[]",
            prompt_fragment=(
                "Prioritize positive evaluation evidence grounded in citation_text."
            ),
            scoring_rules_json=json.dumps(
                {
                    "strict_rules": [
                        "requires explicit positive evaluation of the target paper",
                        "capability description alone is insufficient",
                        "limitation feedback and ordinary related work are excluded",
                    ]
                }
            ),
            is_builtin=False,
            is_active=True,
        )
        customized = AnalysisTemplate(
            session_kind="scholar_analysis",
            session_id=30,
            name="positive_evaluation",
            description="用户调整的正向评价",
            template_type="positive_evaluation",
            natural_language_goal="Only match explicit praise selected by this user.",
            target_aspects_json='["positive_evaluation"]',
            positive_keywords_json="[]",
            negative_keywords_json="[]",
            required_evidence_patterns_json="[]",
            prompt_fragment="User-defined instruction.",
            scoring_rules_json="{}",
            is_builtin=False,
            is_active=True,
        )
        db.add_all([legacy, customized])
        db.commit()

        TemplateService(db).get_active_templates(29)
        db.refresh(legacy)
        db.refresh(customized)

    assert "Explicit praise is not required" in legacy.natural_language_goal
    assert "concrete, target-anchored description" in legacy.prompt_fragment
    assert (
        json.loads(legacy.scoring_rules_json)["strict_rules"][0]
        .startswith("a concrete target-anchored method")
    )
    assert customized.natural_language_goal == (
        "Only match explicit praise selected by this user."
    )
    assert customized.prompt_fragment == "User-defined instruction."


def test_enable_disable_template(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = TemplateService(db)
        builtin = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        enabled = service.enable_template(session_id=1, template_id=builtin.id)
        assert enabled.is_active is True
        service.disable_template(session_id=1, template_id=builtin.id)
        active = service.get_active_templates(1)

    assert all(template.template_type != "baseline_or_benchmark" for template in active)


def test_create_custom_template(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        created = TemplateService(db).create_custom_template(
            session_id=1,
            natural_language_goal="我想找大篇幅和我们方法对比的论文",
            template_type="custom",
            positive_keywords=["大篇幅", "方法对比"],
        )

    assert created.id is not None
    assert created.is_active is True
    assert "方法对比" in created.prompt_fragment


def test_custom_template_is_saved_with_goal_and_keywords(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        created = TemplateService(db).create_custom_template(
            session_id=1,
            template_name="精细感知能力佐证",
            natural_language_goal="判断正文是否明确确认目标论文具有精细振动感知能力。",
            template_type="custom",
            positive_keywords=["fine-grained vibration", "high precision"],
            negative_keywords=["related work only"],
            required_patterns=["vibration"],
            allowed_evidence_types=["capability_recognition"],
            strict_rules=["body evidence only", "title-only does not satisfy"],
            instruction_text="必须结合正文语义和目标引用编号判断。",
            min_citation_chars=40,
            min_citation_words=6,
            require_target_marker=True,
            allow_grouped_citation=False,
            auto_include_in_report=True,
        )
        rules = json.loads(created.scoring_rules_json)

    assert created.natural_language_goal.startswith("判断正文")
    assert json.loads(created.positive_keywords_json) == ["fine-grained vibration", "high precision"]
    assert json.loads(created.negative_keywords_json) == ["related work only"]
    assert json.loads(created.required_evidence_patterns_json) == ["vibration"]
    assert rules["min_citation_chars"] == 40
    assert rules["min_citation_words"] == 6
    assert rules["require_target_marker"] is True
    assert rules["allow_grouped_citation"] is False
    assert rules["auto_include_in_report"] is True
    assert rules["allowed_evidence_types"] == ["capability_recognition"]
    assert rules["strict_rules"] == ["body evidence only", "title-only does not satisfy"]
    assert created.prompt_fragment == "必须结合正文语义和目标引用编号判断。"


def test_custom_template_partial_concept_match_becomes_review_candidate(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="自定义能力评价",
            natural_language_goal="查找目标论文在移动检测中的能力评价。",
            positive_keywords=["moving tag", "detection efficiency"],
            required_patterns=["explicit performance table"],
            require_target_marker=True,
            allow_grouped_citation=False,
        )
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_summary",
            quote=(
                "Target Paper [23] improves moving tag detection efficiency "
                "with phase-profile features."
            ),
        )

    assert result["matched_template_ids"] == [template.id]
    assert result["strong_matched_template_ids"] == []
    assert result["template_match_level"] == "candidate"
    assert result["template_strongly_satisfied"] is False


def test_long_context_template_uses_min_words_not_keyword(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        created = TemplateService(db).create_custom_template(
            session_id=1,
            natural_language_goal="我想找超过100字的长引用",
            template_type="long_context_citation",
            positive_keywords=["compare"],
            min_citation_words=100,
            require_target_marker=True,
        )
        rules = json.loads(created.scoring_rules_json)

    assert rules["min_citation_words"] == 100
    assert "100 words" not in created.positive_keywords_json


def test_custom_template_100_words_not_treated_as_literal_keyword(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        created = TemplateService(db).create_custom_template(
            session_id=1,
            natural_language_goal="我想找超过100字的长引用",
            template_type="long_context_citation",
            positive_keywords=["compare"],
            min_citation_words=100,
        )

    assert "100 words" not in created.positive_keywords_json
    assert "compare" in created.positive_keywords_json


def test_long_context_template_scores_long_citation_text(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        template = TemplateService(db).create_custom_template(
            session_id=1,
            natural_language_goal="我想找超过100字的长引用",
            template_type="long_context_citation",
            min_citation_chars=100,
            require_target_marker=True,
        )
        from app.analysis.template_matching import match_template_terms

        terms, reason, score = match_template_terms(
            template,
            ("[36] " + "long citation text " * 20),
        )

    assert terms
    assert score > 0


def test_template_type_dropdown_contains_long_context_citation(client):
    response = client.get("/scholar-sessions/9/templates")

    assert response.status_code == 200
    assert 'value="long_context_citation"' in response.text


def test_template_detail_shows_structured_rules(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        created = TemplateService(db).create_custom_template(
            session_id=9,
            natural_language_goal="我想找超过100字的长引用",
            template_type="long_context_citation",
            min_citation_words=100,
            require_target_marker=True,
            allow_grouped_citation=True,
        )
        template_id = created.id

    response = client.get(f"/scholar-sessions/9/templates/{template_id}")

    assert response.status_code == 200
    assert "模板类型：大篇幅/长上下文引用" in response.text
    assert "citation_text 至少达到评分规则中的最小字符数或词数" in response.text


def test_template_ui_explains_positive_keywords(client):
    response = client.get("/scholar-sessions/9/templates")

    assert response.status_code == 200
    assert "正向关键词只用于语义关键词" in response.text


def test_templates_page_empty_custom_enhancement_message(client):
    response = client.get("/scholar-sessions/9/templates")

    assert response.status_code == 200
    assert "暂无启用自定义增强模板" in response.text
    assert "系统仍会使用内置证据类型进行基础分析" in response.text


def test_custom_template_persists(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        created = TemplateService(db).create_custom_template(
            session_id=3,
            natural_language_goal="我想找院士或 Fellow 正面评价我们的论文",
            template_type="positive_evaluation",
            positive_keywords=["Fellow", "positive"],
        )
        db.expire_all()
        active = TemplateService(db).get_active_templates(3)

    assert any(template.id == created.id for template in active)


def test_template_affects_queue_score(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_edge_for_template_queue(db)
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        service.enable_template(session_id=session_id, template_id=baseline.id)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]
        reasons = json.loads(item.priority_reasons_json)

    assert item.priority_score > 50
    assert any(reason["reason"].startswith("template_match:") for reason in reasons)


def test_template_reason_recorded_in_priority_reasons(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_edge_for_template_queue(db)
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        service.enable_template(session_id=session_id, template_id=baseline.id)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]

    assert "template_match:" in item.priority_reasons_json
    assert "benchmark" in item.priority_reasons_json.lower()


def test_prompt_includes_active_template_fragments(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        template = TemplateService(db).create_custom_template(
            session_id=2,
            natural_language_goal="我想找被称为首次提出的引用",
            template_type="first_or_seminal_claim",
            positive_keywords=["first", "首次"],
        )
        prompt = build_citation_analysis_prompt(
            anchor=type("Anchor", (), {"title": "Target"})(),
            candidate_spans=[],
            template_prompt_fragments=[template.prompt_fragment],
        )

    assert template.prompt_fragment in prompt
    assert "citation_text" in prompt
    assert "grouped citation" in prompt


def test_evidence_template_matching(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, evidence_id = seed_evidence_for_templates(db, tmp_path)
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        service.enable_template(session_id=session_id, template_id=baseline.id)
        matches = service.match_templates_for_evidence(evidence_id)

    assert matches
    assert "benchmark" in matches[0].matched_terms_json.lower()


def test_disabled_template_not_used(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, evidence_id = seed_evidence_for_templates(db, tmp_path)
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        service.enable_template(session_id=session_id, template_id=baseline.id)
        service.disable_template(session_id=session_id, template_id=baseline.id)
        matches = service.match_templates_for_evidence(evidence_id)

    assert matches == []


def test_disabled_template_not_used_for_queue_score(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id = seed_edge_for_template_queue(db)
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        service.enable_template(session_id=session_id, template_id=baseline.id)
        service.disable_template(session_id=session_id, template_id=baseline.id)
        item = make_queue_service(db, tmp_path).build_queue(session_id)[0]

    assert "template_match:" not in item.priority_reasons_json


def test_disabled_template_not_in_scholar_prompt(db_session_factory, tmp_path, monkeypatch):
    provider = RecordingNoFindingsLlmProvider()
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text="Cited Scholar Paper is used as a benchmark baseline.",
        )
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        prompt_fragment = baseline.prompt_fragment
        enabled = service.enable_template(session_id=session_id, template_id=baseline.id)
        service.disable_template(session_id=session_id, template_id=enabled.id)
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )

    assert provider.requests
    assert prompt_fragment not in provider.requests[0].prompt_text


def test_highlight_cards_grouped_by_template(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, evidence_id = seed_evidence_for_templates(db, tmp_path)
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        service.enable_template(session_id=session_id, template_id=baseline.id)
        service.match_templates_for_evidence(evidence_id)
        card = HighlightCardService(db).generate_cards_from_evidence(session_id)[0]
        report = ScholarReportService(db).build_report_markdown(session_id)

    assert card.card_type == "baseline_or_benchmark"
    assert "尚未运行 fulltext_template_direct 分析" in report
    assert "### baseline_or_benchmark" not in report


def test_template_match_terms_visible(client, db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, evidence_id = seed_evidence_for_templates(db, tmp_path)
        service = TemplateService(db)
        baseline = next(
            template
            for template in service.list_builtin_templates()
            if template.template_type == "baseline_or_benchmark"
        )
        service.enable_template(session_id=session_id, template_id=baseline.id)
        service.match_templates_for_evidence(evidence_id)

    response = client.get(f"/scholar-sessions/{session_id}/evidence?mode=debug")

    assert response.status_code == 200
    assert "benchmark" in response.text
    assert "Template match" in response.text


def test_template_management_routes_enable_disable_and_create_custom(client, db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        builtin = next(
            template
            for template in TemplateService(db).list_builtin_templates()
            if template.template_type == "positive_evaluation"
        )
        builtin_id = builtin.id

    response = client.get("/scholar-sessions/9/templates")
    assert response.status_code == 200
    assert "Built-in templates" in response.text

    response = client.post(
        "/scholar-sessions/9/templates/enable",
        data={"template_id": builtin_id},
    )
    assert response.status_code == 200

    with Session(db_session_factory.kw["bind"]) as db:
        active = TemplateService(db).get_active_templates(9)
        assert any(template.template_type == "positive_evaluation" for template in active)
        enabled_id = next(
            template.id
            for template in active
            if template.template_type == "positive_evaluation"
        )

    response = client.post(
        "/scholar-sessions/9/templates/custom",
        data={
            "natural_language_goal": "我想找被称为首次提出的引用",
            "template_type": "first_or_seminal_claim",
            "positive_keywords": "first,首次",
        },
    )
    assert response.status_code == 200

    response = client.post(
        "/scholar-sessions/9/templates/disable",
        data={"template_id": enabled_id},
    )
    assert response.status_code == 200

    with Session(db_session_factory.kw["bind"]) as db:
        active = TemplateService(db).get_active_templates(9)

    assert any(template.template_type == "first_or_seminal_claim" for template in active)
    assert all(template.template_type != "positive_evaluation" for template in active)


def test_active_templates_included_in_fulltext_prompt(db_session_factory, tmp_path, monkeypatch):
    provider = RecordingNoFindingsLlmProvider()
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text="Cited Scholar Paper is discussed in the body.",
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            natural_language_goal="RFID 亚毫米级感知能力佐证",
            template_type="custom",
            positive_keywords=["RFID", "sub-mm", "vibration sensing"],
        )
        template_id = template.id
        ScholarFulltextService(db).analyze_queue_items(
            session_id=session_id,
            queue_item_ids=[item_id],
            analysis_scope="scholar_queue",
        )

    assert provider.requests
    prompt = provider.requests[0].prompt_text
    assert '"template_id":' in prompt
    assert str(template_id) in prompt
    assert "RFID 亚毫米级感知能力佐证" in prompt
    assert "matched_template_ids" in prompt


def test_active_custom_template_passed_to_fulltext_template_direct_prompt(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "[4] Target Paper.",
            "paper_level_summary_zh": "无证据。",
            "evidences": [],
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text="Body discussion [4].\n\nReferences\n[4] Target Paper.",
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="用户精细感知模板",
            natural_language_goal="判断目标论文是否被正文明确用于精细振动感知。",
            positive_keywords=["fine-grained vibration", "sub-millimeter"],
            negative_keywords=["reference-only"],
            required_patterns=["vibration"],
            strict_rules=["plain related work does not satisfy"],
            instruction_text="Do not satisfy from title-only evidence.",
            require_target_marker=True,
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        diagnostics = json.loads(result.candidate_spans_json)
        template_id = template.id

    prompt = provider.requests[0].prompt_text
    assert str(template_id) in prompt
    assert "用户精细感知模板" in prompt
    assert "判断目标论文是否被正文明确用于精细振动感知" in prompt
    assert "fine-grained vibration" in prompt
    assert "reference-only" in prompt
    assert "plain related work does not satisfy" in prompt
    assert diagnostics["active_template_count"] == 1
    assert "用户精细感知模板" in diagnostics["active_template_names"]


def test_no_hardcoded_rfid_submm_template_required(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        service = TemplateService(db)
        builtins = service.list_builtin_templates()
        custom = service.create_custom_template(
            session_id=1,
            template_name="用户定义的亚毫米能力问题",
            natural_language_goal="判断正文是否明确佐证目标论文检测亚毫米级振动。",
            positive_keywords=["sub-millimeter-level vibrations", "detecting"],
            required_patterns=["sub-millimeter-level vibrations"],
            require_target_marker=True,
        )
        result = service.evaluate_finding_templates(
            session_id=1,
            finding_payload={"reasoning": "正文明确描述检测能力。"},
            citation_text="The method is used for detecting sub-millimeter-level vibrations [4].",
            evidence_context="The method is used for detecting sub-millimeter-level vibrations [4].",
            target_reference_marker="[4]",
            cited_paper_title="Target Paper",
        )
        builtin_names = [template.name for template in builtins]
        custom_id = custom.id

    assert "rfid_submm_capability" not in builtin_names
    assert result["template_satisfied"] is True
    assert result["matched_template_ids"] == [custom_id]


def test_custom_template_applies_to_fulltext_template_direct_result(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "The method is used for detecting sub-millimeter-level vibrations [4]."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "[4] Target Paper.",
            "paper_level_summary_zh": "正文提供精细振动能力佐证。",
            "evidences": [
                {
                    "recommendation": "review",
                    "claim_type": "custom_template_evidence",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[4] Target Paper.",
                    "why_this_judgment_zh": "正文明确描述检测能力。",
                    "copy_ready_zh": "目标论文被用于精细振动检测。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[4] Target Paper.",
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="用户精细振动能力模板",
            natural_language_goal="判断正文是否明确佐证目标论文检测精细振动。",
            positive_keywords=["sub-millimeter-level vibrations", "detecting"],
            required_patterns=["sub-millimeter-level vibrations"],
            require_target_marker=True,
            auto_include_in_report=True,
        )
        template_id = template.id
        set_model_template_decision(
            provider,
            [template_id],
            reason=(
                "The body explicitly attributes sub-millimeter-level vibrations "
                "detection to the target reference."
            ),
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]
        template_id = template.id

    assert evidence["template_satisfied"] is True
    assert evidence["matched_template_ids"] == [template_id]
    assert "sub-millimeter-level vibrations" in evidence["template_match_reason"]
    assert evidence["recommendation"] == "include"
    assert evidence["claim_type"] == "custom_template_evidence"


def test_title_only_does_not_satisfy_custom_template(db_session_factory):
    with Session(db_session_factory.kw["bind"]) as db:
        template = TemplateService(db).create_custom_template(
            session_id=1,
            template_name="标题不能命中",
            natural_language_goal="判断正文是否提供精细能力佐证。",
            positive_keywords=["sub-millimeter"],
            require_target_marker=True,
        )
        result = TemplateService(db).evaluate_finding_templates(
            session_id=1,
            finding_payload={"reasoning": "title-only"},
            citation_text="Target Paper: Sub-millimeter Sensing [4]",
            evidence_context="References: Target Paper: Sub-millimeter Sensing [4]",
            target_reference_marker="[4]",
            cited_paper_title="Target Paper: Sub-millimeter Sensing",
        )

    assert result["matched_template_ids"] != [template.id]
    assert result["template_satisfied"] is False
    assert "title-only" in result["template_failure_reason"]


def test_unresolved_reference_custom_template_goes_to_review(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "The method is used for detecting sub-millimeter-level vibrations [4]."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "",
            "paper_level_summary_zh": "强候选。",
            "evidences": [
                {
                    "recommendation": "include",
                    "claim_type": "capability_recognition",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "",
                    "why_this_judgment_zh": "正文明确检测能力。",
                    "copy_ready_zh": "精细振动检测候选。",
                    "confidence": "high",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote,
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="用户精细振动能力模板",
            natural_language_goal="判断正文是否明确佐证目标论文检测精细振动。",
            positive_keywords=["sub-millimeter-level vibrations", "detecting"],
            required_patterns=["sub-millimeter-level vibrations"],
            require_target_marker=True,
            auto_include_in_report=True,
        )
        set_model_template_decision(
            provider,
            [template.id],
            reason=(
                "The body satisfies the custom capability goal, but the "
                "reference entry remains unresolved."
            ),
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        evidence = json.loads(result.parsed_result_json)["evidences"][0]

    assert evidence["template_satisfied"] is True
    assert evidence["reference_match_status"] == "unresolved"
    assert evidence["recommendation"] == "review"


def test_custom_template_debug_fields_are_hidden_in_formal_report(
    db_session_factory,
    tmp_path,
    monkeypatch,
):
    quote = "Target Paper demonstrates precise sensing [4]."
    provider = CapturingTemplateDirectProvider(
        {
            "target_reference_marker": "[4]",
            "target_reference_entry": "[4] Target Paper.",
            "paper_level_summary_zh": "能力佐证。",
            "evidences": [
                {
                    "recommendation": "review",
                    "claim_type": "capability_recognition",
                    "evidence_quote": quote,
                    "evidence_context": quote,
                    "reference_entry": "[4] Target Paper.",
                    "why_this_judgment_zh": "正文明确能力。",
                    "copy_ready_zh": "可作为能力候选。",
                    "confidence": "medium",
                }
            ],
        }
    )
    monkeypatch.setattr("app.services.scholar_fulltext_service.get_llm_provider", lambda: provider)
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
            text=quote + "\n\nReferences\n[4] Target Paper.",
        )
        TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="精确感知模板",
            natural_language_goal="判断正文是否确认精确感知能力。",
            positive_keywords=["precise sensing"],
            require_target_marker=True,
        )
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="fulltext_template_direct",
        )
        report = ScholarReportService(db).build_report_markdown(session_id)
        debug_rows = ScholarFulltextService(db).list_analysis_debug_rows(session_id)

    assert "matched_template_ids" not in report
    assert "template_failure_reason" not in report
    assert "matched_template_ids" in debug_rows[0]["parsed_findings_preview"]
    assert "template_satisfied" in debug_rows[0]["parsed_findings_preview"]


def test_custom_template_debug_fields_visible_in_debug_view(
    client,
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path, target_title="Target Paper")
        item = db.get(DeepAnalysisQueueItem, item_id)
        db.add(
            FulltextAnalysisResult(
                scholar_session_id=session_id,
                queue_item_id=item_id,
                citation_edge_id=item.citation_edge_id,
                analysis_scope="fulltext_template_direct",
                status="succeeded",
                candidate_spans_json=json.dumps(
                    {
                        "active_template_count": 1,
                        "active_template_names": ["用户能力佐证模板"],
                        "prompt_contains_templates": True,
                        "template_satisfied_count": 1,
                        "template_unsatisfied_count": 0,
                        "prompt_template_snapshot_json": json.dumps(
                            [{"template_id": 91, "goal": "判断正文能力佐证"}],
                            ensure_ascii=False,
                        ),
                    },
                    ensure_ascii=False,
                ),
                parsed_result_json=json.dumps(
                    {
                        "evidences": [
                            {
                                "evidence_quote": "Target Paper demonstrates the capability [4].",
                                "matched_template_ids": [91],
                                "template_satisfied": True,
                                "template_match_reason": "正文概念与目标引用编号共同满足模板。",
                                "template_failure_reason": "",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()

    response = client.get(f"/scholar-sessions/{session_id}/analysis-debug")

    assert response.status_code == 200
    assert "用户能力佐证模板" in response.text
    assert "matched_template_ids" in response.text
    assert "template_match_reason" in response.text


def test_fulltext_result_records_template_snapshot(db_session_factory, tmp_path, monkeypatch):
    provider = RecordingNoFindingsLlmProvider()
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(db, tmp_path)
        TemplateService(db).create_custom_template(
            session_id=session_id,
            natural_language_goal="first / pioneering / early / seminal 首次开创性模板",
            template_type="first_or_seminal_claim",
            positive_keywords=["first", "pioneering", "seminal"],
        )
        result = ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="scholar_queue",
        )
        payload = json.loads(result.candidate_spans_json)

    assert payload["active_template_count"] >= 1
    assert payload["prompt_contains_templates"] is True
    assert "first" in payload["prompt_template_snapshot_json"].lower()


def test_custom_template_affects_evidence_classification(db_session_factory, tmp_path, monkeypatch):
    provider = RecordingFindingsLlmProvider(
        {
            "findings": [
                {
                    "evidence_type": "method_foundation",
                    "stance": "positive",
                    "mention_type": "explicit_target",
                    "citation_text": "Sub-mm RFID Vibration Sensing captures loudspeaker vibration with sub-mm precision.",
                    "reasoning": "The body quote explicitly describes RFID loudspeaker vibration and sub-mm precision.",
                    "keywords": ["sub-mm", "RFID", "loudspeaker vibration"],
                    "keep": True,
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Sub-mm RFID Vibration Sensing",
            text="Sub-mm RFID Vibration Sensing captures loudspeaker vibration with sub-mm precision.",
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="RFID 亚毫米级感知能力佐证",
            natural_language_goal="判断正文是否明确佐证目标论文实现亚毫米级振动感知能力。",
            template_type="custom",
            positive_keywords=["sub-mm", "RFID", "loudspeaker vibration"],
            required_patterns=["sub-mm"],
            require_target_marker=False,
        )
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="scholar_queue",
        )
        evidence = db.query(StrongEvidence).filter_by(scholar_session_id=session_id).one()
        template_id = template.id

    assert evidence.template_satisfied is True
    assert "sub-mm" in (evidence.template_match_reason or "")
    assert json.loads(evidence.matched_template_ids_json) == [template_id]


def test_plain_rfid_related_work_does_not_satisfy_custom_submm_template(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Sub-mm RFID Vibration Sensing",
        )
        service = TemplateService(db)
        service.create_custom_template(
            session_id=session_id,
            natural_language_goal="RFID 亚毫米级感知能力佐证",
            template_type="custom",
            positive_keywords=["RFID", "sub-mm", "vibration sensing"],
        )
        result = service.evaluate_finding_templates(
            session_id=session_id,
            finding_payload={"evidence_type": "background", "reasoning": "plain RFID related work"},
            citation_text="RFID [6] is listed for eavesdropping in related work.",
            evidence_context="RFID [6] is listed for eavesdropping in related work.",
            target_reference_marker="[6]",
            cited_paper_title="Sub-mm RFID Vibration Sensing",
        )

    assert result["template_satisfied"] is False
    assert "plain related work" in result["template_failure_reason"] or "substantive" in result["template_failure_reason"]


def test_first_pioneering_template_requires_explicit_first_expression(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _item_id = seed_queue_item(db, tmp_path)
        service = TemplateService(db)
        service.create_custom_template(
            session_id=session_id,
            natural_language_goal="first / pioneering / early / seminal 首次开创性模板",
            template_type="first_or_seminal_claim",
            positive_keywords=["first", "pioneering", "seminal"],
        )
        negative = service.evaluate_finding_templates(
            session_id=session_id,
            finding_payload={"evidence_type": "representative_work", "reasoning": "related work"},
            citation_text="Cited Scholar Paper is related prior work.",
            target_reference_marker="",
            cited_paper_title="Cited Scholar Paper",
        )
        positive = service.evaluate_finding_templates(
            session_id=session_id,
            finding_payload={"evidence_type": "first_or_seminal_claim", "reasoning": "explicit first"},
            citation_text="Cited Scholar Paper is the first system to solve this problem.",
            target_reference_marker="",
            cited_paper_title="Cited Scholar Paper",
        )

    assert negative["template_satisfied"] is False
    assert "no explicit first/pioneering expression" in negative["template_failure_reason"]
    assert positive["template_satisfied"] is True
    assert "the first" in positive["template_match_reason"]


def test_first_claim_scope_does_not_match_target_when_first_refers_to_tagmic(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _item_id = seed_queue_item(db, tmp_path, target_title="Wang RFID Sensing")
        service = TemplateService(db)
        service.create_custom_template(
            session_id=session_id,
            natural_language_goal="first / pioneering / early / seminal 首次开创性模板",
            template_type="first_or_seminal_claim",
            positive_keywords=["first", "pioneering", "seminal"],
        )
        result = service.evaluate_finding_templates(
            session_id=session_id,
            finding_payload={"evidence_type": "first_or_seminal_claim", "reasoning": "TagMic is first"},
            citation_text="TagMic is the first system to sense speech vibrations, unlike Wang RFID Sensing [23].",
            target_reference_marker="[23]",
            cited_paper_title="Wang RFID Sensing",
        )

    assert result["template_satisfied"] is False
    assert "does not modify the target paper" in result["template_failure_reason"]


def test_rfid_submm_direct_claim_requires_target_anchor(db_session_factory, tmp_path):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _item_id = seed_queue_item(db, tmp_path, target_title="Sub-mm RFID Vibration Sensing")
        service = TemplateService(db)
        service.create_custom_template(
            session_id=session_id,
            natural_language_goal="RFID 亚毫米级感知能力佐证",
            template_type="custom",
            positive_keywords=["RFID", "sub-mm", "vibration sensing"],
        )
        result = service.evaluate_finding_templates(
            session_id=session_id,
            finding_payload={"evidence_type": "precision_claim", "reasoning": "no target anchor"},
            citation_text="Another RFID system reaches sub-mm vibration sensing accuracy [99].",
            evidence_context="Another RFID system reaches sub-mm vibration sensing accuracy [99].",
            target_reference_marker="[23]",
            cited_paper_title="Sub-mm RFID Vibration Sensing",
        )

    assert result["template_satisfied"] is False
    assert "does not anchor to target paper" in result["template_failure_reason"]


def test_strong_evidence_and_highlight_card_record_matched_template(db_session_factory, tmp_path, monkeypatch):
    provider = RecordingFindingsLlmProvider(
        {
            "findings": [
                {
                    "evidence_type": "first_or_seminal_claim",
                    "stance": "positive",
                    "mention_type": "explicit_target",
                    "citation_text": "Cited Scholar Paper is the first system to solve this problem.",
                    "reasoning": "The quote explicitly says the target is the first system.",
                    "keywords": ["first system"],
                    "keep": True,
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text="Cited Scholar Paper is the first system to solve this problem.",
        )
        builtin = next(
            template
            for template in TemplateService(db).list_builtin_templates()
            if template.template_type == "first_or_pioneering_claim"
        )
        TemplateService(db).enable_template(session_id=session_id, template_id=builtin.id)
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="scholar_queue",
        )
        evidence = db.query(StrongEvidence).filter_by(scholar_session_id=session_id).one()
        card = HighlightCardService(db).generate_cards_from_evidence(session_id)[0]

    assert evidence.template_satisfied is True
    assert card.template_satisfied is True
    assert "首次" in (card.matched_template_names or "")
    assert card.template_match_reason


def test_template_filter_view_and_report_include_template_reason(client, db_session_factory, tmp_path, monkeypatch):
    provider = RecordingFindingsLlmProvider(
        {
            "findings": [
                {
                    "evidence_type": "first_or_seminal_claim",
                    "stance": "positive",
                    "mention_type": "explicit_target",
                    "citation_text": "Cited Scholar Paper is the first system to solve this problem.",
                    "reasoning": "The quote explicitly says first.",
                    "keywords": ["first system"],
                    "keep": True,
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.services.scholar_fulltext_service.get_llm_provider",
        lambda: provider,
    )
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            text="Cited Scholar Paper is the first system to solve this problem.",
        )
        builtin = next(
            template
            for template in TemplateService(db).list_builtin_templates()
            if template.template_type == "first_or_pioneering_claim"
        )
        enabled = TemplateService(db).enable_template(session_id=session_id, template_id=builtin.id)
        enabled_id = enabled.id
        ScholarFulltextService(db).analyze_single_queue_item(
            queue_item_id=item_id,
            analysis_scope="scholar_queue",
        )
        HighlightCardService(db).generate_cards_from_evidence(session_id)

    response = client.get(f"/scholar-sessions/{session_id}/report-workspace?view=template:{enabled_id}")
    report = client.get(f"/scholar-sessions/{session_id}/exports/highlight_cards.md")

    assert response.status_code == 200
    assert "命中模板" in response.text
    assert "模板判断理由" in response.text
    assert "尚未运行 fulltext_template_direct 分析" in report.text
    assert "模板命中原因" not in report.text
    assert "template_failure_reason" not in report.text


def _enable_builtin_for_test(db, session_id, template_type):
    service = TemplateService(db)
    builtin = next(
        template
        for template in service.list_builtin_templates()
        if template.template_type == template_type
    )
    return service.enable_template(session_id=session_id, template_id=builtin.id)


def _evaluate_active_templates(
    db,
    *,
    session_id,
    claim_type,
    quote,
    context=None,
    marker="[23]",
    target_title="Target Paper",
    reference_match_status="matched",
    target_anchor_inherited=False,
):
    return TemplateService(db).evaluate_finding_templates(
        session_id=session_id,
        finding_payload={
            "claim_type": claim_type,
            "reference_match_status": reference_match_status,
            "target_anchor_inherited": target_anchor_inherited,
        },
        citation_text=quote,
        evidence_context=context or quote,
        target_reference_marker=marker,
        cited_paper_title=target_title,
    )


def test_first_seminal_template_contract_positive_and_scope_negative(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(
            db, session_id, "first_or_seminal_claim"
        )
        enabled_id = enabled.id
        positive = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="first_or_seminal_claim",
            quote=(
                "Target Paper [23] was the first work to recover speech by "
                "sensing speaker vibrations."
            ),
        )
        negative = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="first_or_seminal_claim",
            quote=(
                "The first approach [17] used radar, while Target Paper [23] "
                "used another sensing method."
            ),
        )

    assert positive["matched_template_ids"] == [enabled_id]
    assert positive["template_satisfied"] is True
    assert negative["matched_template_ids"] == []
    assert negative["template_satisfied"] is False
    assert "does not modify the target paper" in negative["template_failure_reason"]


def test_detailed_comparison_requires_substantive_context(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "detailed_comparison")
        enabled_id = enabled.id
        positive = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="detailed_comparison",
            quote="We compare our method with Target Paper [23] in Table 2.",
            context=(
                "We compare our method with Target Paper [23] in Table 2. "
                "Target Paper reaches 82% accuracy with 40 ms latency, whereas "
                "our method reaches 86% accuracy with 31 ms latency. The "
                "experiment uses the same dataset and reports the error metric."
            ),
        )
        passing_mention = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="detailed_comparison",
            quote="Our method is compared with previous work [23].",
        )

    assert positive["matched_template_ids"] == [enabled_id]
    assert passing_mention["matched_template_ids"] == [enabled_id]
    assert passing_mention["template_match_level"] == "candidate"
    assert passing_mention["template_strongly_satisfied"] is False


def test_baseline_template_requires_experimental_use(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(
            db, session_id, "baseline_or_benchmark"
        )
        enabled_id = enabled.id
        positive = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="baseline_or_benchmark",
            quote="We reproduce Target Paper [23] as a baseline in Table 3.",
            context=(
                "We reproduce Target Paper [23] as a baseline in Table 3. "
                "The experiment compares accuracy and error on the same dataset."
            ),
        )
        ordinary = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="baseline_or_benchmark",
            quote="Related work lists Target Paper [23] as a baseline approach.",
        )

    assert positive["matched_template_ids"] == [enabled_id]
    assert ordinary["matched_template_ids"] == [enabled_id]
    assert ordinary["template_match_level"] == "candidate"
    assert ordinary["template_strongly_satisfied"] is False


def test_positive_evaluation_requires_explicit_targeted_praise(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "positive_evaluation")
        enabled_id = enabled.id
        positive = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_recognition",
            quote=(
                "Target Paper [23] provides an effective and robust solution "
                "with significantly higher accuracy."
            ),
        )
        grouped = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="positive_evaluation",
            quote="Prior systems [22], [23] provide effective solutions.",
        )
        limitation = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_recognition",
            quote=(
                "Target Paper [23] is less practical and has limited accuracy."
            ),
        )

    assert positive["matched_template_ids"] == [enabled_id]
    assert grouped["matched_template_ids"] == [enabled_id]
    assert grouped["template_match_level"] == "candidate"
    assert grouped["template_strongly_satisfied"] is False
    assert limitation["matched_template_ids"] == []
    assert "limitation feedback" in limitation["template_failure_reason"]


def test_limitation_template_accepts_limitation_feedback(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(
            db,
            session_id,
            "limitation_or_negative",
        )
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="limitation_feedback",
            quote=(
                "Target Paper [23] is less practical because it requires "
                "pre-installed tags."
            ),
        )

    assert result["matched_template_ids"] == [enabled.id]
    assert result["template_satisfied"] is True
    assert "evidence type limitation_feedback is not allowed" not in result[
        "template_failure_reason"
    ]


def test_positive_evaluation_broad_candidate_does_not_become_strong_match(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "positive_evaluation")
        enabled_id = enabled.id
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_summary",
                quote=(
                    "Wang et al. [23] extract phase profiles and link frequency "
                    "to distinguish moving tags by location."
                ),
        )

    assert result["matched_template_ids"] == [enabled_id], result
    assert result["template_satisfied"] is True
    assert result["template_match_level"] == "candidate"
    assert result["template_strongly_satisfied"] is False


def test_positive_language_can_be_strong_even_when_llm_called_it_ordinary(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "positive_evaluation")
        enabled_id = enabled.id
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="ordinary_reference",
            quote=(
                "Target Paper [23] improves detection efficiency and provides "
                "an effective solution for moving-tag recognition."
            ),
        )

    assert result["matched_template_ids"] == [enabled_id]
    assert result["strong_matched_template_ids"] == [enabled_id]
    assert result["template_match_level"] == "strong"


def test_brief_targeted_comparison_is_candidate_not_strong(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "detailed_comparison")
        enabled_id = enabled.id
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="method_summary",
            quote="Compared with Target Paper [23], our method uses a different decoder.",
        )

    assert result["matched_template_ids"] == [enabled_id]
    assert result["template_match_level"] == "candidate"
    assert result["template_strongly_satisfied"] is False


def test_targeted_model_description_is_theoretical_candidate(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "theoretical_foundation")
        enabled_id = enabled.id
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="method_summary",
            quote=(
                "Target Paper [23] describes a phase model for moving-tag detection."
            ),
        )

    assert result["matched_template_ids"] == [enabled_id]
    assert result["template_match_level"] == "candidate"
    assert result["template_strongly_satisfied"] is False


def test_method_foundation_contract_distinguishes_summary_and_adoption(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "method_foundation")
        summary = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="method_summary",
            quote=(
                "Target Paper [23] extracts phase profiles to distinguish "
                "moving tags."
            ),
        )
        adoption = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="method_use",
            quote=(
                "Our system adopts the phase extraction method from "
                "Target Paper [23]."
            ),
        )

    assert summary["matched_template_ids"] == [enabled.id]
    assert summary["template_match_level"] == "candidate"
    assert adoption["matched_template_ids"] == [enabled.id]
    assert adoption["template_match_level"] == "strong"


def test_custom_neutral_attitude_template_is_mutually_exclusive(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="中性评价",
            natural_language_goal="判断引用是否既不属于正向评价也不属于负面评价",
            auto_include_in_report=True,
        )
        template_id = template.id
        positive = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="positive_evaluation",
            quote="Target Paper [23] provides an effective and robust solution.",
        )
        neutral = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="method_summary",
            quote="Target Paper [23] estimates 6-DoF pose from moire patterns.",
        )
        negative = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="limitation_feedback",
            quote="Target Paper [23] is limited to controlled environments.",
        )

    assert template_id not in positive["matched_template_ids"]
    assert template_id in neutral["strong_matched_template_ids"]
    assert template_id not in negative["matched_template_ids"]


def test_grouped_citation_can_reach_candidate_template_matching(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        _enable_builtin_for_test(db, session_id, "positive_evaluation")
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_summary",
            quote="Prior systems [22], [23] use phase models for tag detection.",
        )

    assert result["matched_template_ids"]
    assert result["template_match_level"] == "candidate"
    assert "grouped citation" not in result["template_failure_reason"]


def test_positive_template_failure_text_does_not_render_first_claim():
    interpretation = interpret_evidence(
        evidence_quote=(
            "Wang et al. [23] extract phase profiles to improve detection efficiency."
        ),
        evidence_context="The paragraph summarizes several related methods.",
        card_type="positive_evaluation",
        evidence_type="positive_evaluation",
        stance="positive",
        mention_type="template_direct",
        citing_paper_title="Citing Paper",
        cited_paper_title="Target Paper",
        target_reference_marker="[23]",
        template_match_reason="target-specific capability description",
        template_satisfied=True,
        template_failure_reason=(
            "首次/开创性评价: no explicit first/pioneering expression in body text"
        ),
        anchor_validation_status="valid",
    )

    assert interpretation.judgment_label != "首次/开创性明确佐证"
    assert "first / pioneering / seminal" not in interpretation.judgment_basis_zh


def test_method_or_capability_summary_template_requires_target_specific_body_claim(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="方法或能力概述",
            natural_language_goal="识别正文对目标论文方法、机制或能力的具体概述。",
            template_type="method_or_capability_summary",
            require_target_marker=True,
            allow_grouped_citation=False,
        )
        positive = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_summary",
            quote=(
                "Wang et al. [26] proposed a moving label detection mechanism "
                "that uses collision signals to improve time efficiency."
            ),
            marker="[26]",
            target_title="Target Paper",
        )
        grouped = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_summary",
            quote=(
                "Prior systems [25], [26] proposed several sensing mechanisms."
            ),
            marker="[26]",
            target_title="Target Paper",
        )
        reference_only = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_summary",
            quote="References [26] Wang et al. Target Paper. Journal, 2021.",
            marker="[26]",
            target_title="Target Paper",
        )

    assert positive["matched_template_ids"] == [template.id]
    assert grouped["matched_template_ids"] == [template.id]
    assert grouped["template_match_level"] == "candidate"
    assert "grouped citation" not in grouped["template_failure_reason"]
    assert reference_only["matched_template_ids"] == []
    assert "reference-only" in reference_only["template_failure_reason"]


def test_fulltext_template_direct_prompt_requests_high_recall_candidates():
    prompt = build_fulltext_template_direct_prompt(
        citing_paper_title="Citing Paper",
        cited_paper_title="Target Paper",
        full_text="Body text.",
        template_prompt_fragments=[],
    )

    assert "Return every potentially target-related body-text candidate" in prompt
    assert "deterministic reference validation" in prompt
    assert '"candidate_reason"' in prompt
    assert '"citation_markers"' in prompt
    assert "Do not omit a candidate merely because it does not satisfy an active template" in prompt
    assert "your semantic decision determines" in prompt
    assert "positive, neutral, and negative/limitation templates" in prompt
    assert "Do not require literal template keywords" in prompt
    assert "Never use generic wording" in prompt
    assert "concrete subject, action, capability/effect/limitation" in prompt
    assert "what method/theory/mechanism it introduced or used" in prompt
    assert "Do not claim 'first', 'pioneering'" in prompt
    assert "hints, not mandatory gates" in prompt
    assert "Do not reject a template solely" in prompt


def test_positive_evaluation_accepts_safe_named_method_anchor_inheritance(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        enabled = _enable_builtin_for_test(db, session_id, "positive_evaluation")
        enabled_id = enabled.id
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="capability_recognition",
            quote=(
                "Tag-Bug effectively captures loudspeaker vibrations for "
                "through-the-wall eavesdropping."
            ),
            context=(
                "Target Paper [23] introduces a method called Tag-Bug. "
                "Tag-Bug effectively captures loudspeaker vibrations for "
                "through-the-wall eavesdropping."
            ),
            target_anchor_inherited=True,
        )

    assert result["matched_template_ids"] == [enabled_id]
    assert result["template_satisfied"] is True


def test_multiple_active_templates_can_match_one_evidence(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path, target_title="Target Paper")
        first = _enable_builtin_for_test(
            db, session_id, "first_or_seminal_claim"
        )
        positive = _enable_builtin_for_test(
            db, session_id, "positive_evaluation"
        )
        result = _evaluate_active_templates(
            db,
            session_id=session_id,
            claim_type="positive_evaluation",
            quote=(
                "Target Paper [23] was the first work and provides an effective, "
                "robust solution with high accuracy."
            ),
        )

    assert result["template_satisfied"] is True
    assert set(result["matched_template_ids"]) == {first.id, positive.id}


def test_active_template_snapshot_exposes_effective_contract(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        enabled = _enable_builtin_for_test(db, session_id, "positive_evaluation")
        enabled.scoring_rules_json = json.dumps({"template_bonus": 12})
        db.commit()
        snapshot = TemplateService(db).active_template_snapshots(session_id)

    assert snapshot[0]["allowed_evidence_types"]
    assert "positive_evaluation" in snapshot[0]["allowed_evidence_types"]
    assert snapshot[0]["require_target_marker"] is True
    assert snapshot[0]["allow_grouped_citation"] is False


def test_direct_prompt_template_snapshot_delegates_grouped_attribution_to_model(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, _ = seed_queue_item(db, tmp_path)
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="正向能力评价",
            natural_language_goal="判断正文是否明确肯定目标论文的能力。",
            template_type="positive_evaluation",
            allow_grouped_citation=False,
        )
        prompt_snapshot = json.loads(
            format_template_snapshots_for_prompt([template])
        )[0]

    assert prompt_snapshot["configured_allow_grouped_citation"] is False
    assert (
        prompt_snapshot["grouped_citation_policy"]
        == "model_semantic_attribution"
    )
    assert "allow_grouped_citation" not in prompt_snapshot
    assert "required_patterns" not in prompt_snapshot
    assert "allowed_evidence_types" not in prompt_snapshot
    assert "strict_rules" not in prompt_snapshot
    assert "suggested_patterns" in prompt_snapshot
    assert "suggested_evidence_types" in prompt_snapshot
    assert "advisory_notes" in prompt_snapshot
    assert "advisory rather than hard gates" in prompt_snapshot[
        "semantic_decision_policy"
    ]


def test_direct_model_template_match_bypasses_semantic_config_gates(
    db_session_factory,
    tmp_path,
):
    with Session(db_session_factory.kw["bind"]) as db:
        session_id, item_id = seed_queue_item(
            db,
            tmp_path,
            target_title="Target Paper",
        )
        template = TemplateService(db).create_custom_template(
            session_id=session_id,
            template_name="导师语义模板",
            natural_language_goal="判断正文是否认可目标论文的具体方法价值。",
            template_type="custom",
            positive_keywords=["literal-token-not-present"],
            required_patterns=["mandatory-pattern-not-present"],
            allowed_evidence_types=["capability_recognition"],
            strict_rules=["legacy semantic restriction"],
            require_target_marker=True,
        )
        item = db.get(DeepAnalysisQueueItem, item_id)
        result = ScholarFulltextService(db)._apply_active_templates_to_direct_payload(
            item=item,
            payload={
                "evidences": [{
                "recommendation": "include",
                "claim_type": "method_summary",
                "reference_match_status": "matched",
                "reference_alignment_status": "matched",
                "target_anchor_status": "valid",
                "evidence_quote": (
                    "Target Paper [23] extracts phase features to improve "
                    "moving-tag detection efficiency."
                ),
                "matched_template_ids": [template.id],
                "template_satisfied": True,
                "template_match_reason": (
                    "模型结合完整上下文判断该方法描述满足导师目标。"
                ),
                }],
            },
            active_templates=[template],
        )
        evidence = result["evidences"][0]

    assert evidence["matched_template_ids"] == [template.id]
    assert evidence["strong_matched_template_ids"] == [template.id]
    assert evidence["template_match_level"] == "strong"
    assert evidence["recommendation"] == "include"
    assert "not allowed" not in evidence["template_failure_reason"]
    assert "required evidence pattern" not in evidence["template_failure_reason"]

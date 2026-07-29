from types import SimpleNamespace

from app.analysis.llm_parser import (
    parse_template_adjudication_response_with_diagnostics,
)
from app.analysis.prompt_builder import (
    build_template_direct_adjudication_prompt,
)
from app.analysis.template_direct_postprocess import (
    postprocess_template_direct_payload,
)
from app.schemas.llm import TemplateEvidenceAdjudicationResult
from app.services.scholar_fulltext_service import ScholarFulltextService


TARGET_TITLE = "Probing into the Physical Layer: Moving Tag Detection for Large-Scale RFID Systems"
TARGET_ENTRY = (
    "[26] C. Wang et al. Probing into the Physical Layer: Moving Tag "
    "Detection for Large-Scale RFID Systems. 2020."
)


def _postprocess(evidence, *, marker="[26]", entry=TARGET_ENTRY):
    return postprocess_template_direct_payload(
        {
            "target_reference_marker": marker,
            "target_reference_entry": entry,
            "evidences": [evidence],
        },
        citing_paper_title="LD-Recognition",
        cited_paper_title=TARGET_TITLE,
        target_reference_marker=marker,
        target_reference_entry=entry,
        reference_entries_by_marker={marker.strip("[]"): entry},
        target_reference_resolved=True,
    )["evidences"][0]


def _method_evidence():
    quote = (
        "Wang et al. [26] proposed a moving label detection mechanism. "
        "Two physical layer features are extracted from USRP signals, followed "
        "by graph matching and coherent phase variance methods."
    )
    return {
        "recommendation": "exclude",
        "claim_type": "method_summary",
        "evidence_quote": quote,
        "evidence_context": quote,
        "reference_entry": TARGET_ENTRY,
        "why_this_judgment_zh": "正文具体概述目标方法。",
        "copy_ready_zh": "后续论文具体复述了目标方法的技术机制。",
        "confidence": "high",
    }


def _template(template_id=7):
    return SimpleNamespace(
        id=template_id,
        name="详细方法概述",
        description="详细方法概述",
        template_type="method_or_capability_summary",
        natural_language_goal=(
            "判断正文是否具体描述目标论文的机制、信号、特征或算法步骤。"
        ),
        positive_keywords_json="[]",
        negative_keywords_json="[]",
        required_evidence_patterns_json="[]",
        target_aspects_json="[]",
        scoring_rules_json="{}",
        prompt_fragment="不要求赞扬性措辞。",
    )


class AdjudicatingProvider:
    supports_template_adjudication = True
    provider_name = "adjudicating-test"

    def __init__(self, response):
        self.response = TemplateEvidenceAdjudicationResult.model_validate(
            response
        )
        self.requests = []

    def analyze_citation(self, request):
        self.requests.append(request)
        return self.response


def test_verified_method_summary_has_independent_grounding_and_relation():
    evidence = _postprocess(_method_evidence())

    assert evidence["grounding_status"] == "verified"
    assert evidence["evidence_strength"] == "strong"
    assert evidence["template_relation"] == "detailed_method_summary"
    assert evidence["claim_type"] == "method_summary"


def test_reference_mismatch_remains_grounding_mismatch():
    evidence = _postprocess(
        {
            **_method_evidence(),
            "evidence_quote": "Another method [17] extracts phase features.",
        }
    )

    assert evidence["grounding_status"] == "mismatch"
    assert evidence["final_recommendation"] == "exclude"


def test_template_adjudication_parser_preserves_per_template_decisions():
    parsed = parse_template_adjudication_response_with_diagnostics(
        """
        {
          "template_relation": "detailed_method_summary",
          "adjudications": [
            {"template_id": 7, "satisfied": true, "confidence": "high",
             "reason": "The quote describes two features and graph matching."},
            {"template_id": 8, "satisfied": false, "confidence": "high",
             "reason": "No evaluative praise is present."}
          ],
          "why_this_judgment_zh": "原文具体描述了特征和算法步骤。",
          "copy_ready_zh": "后续工作具体概述了目标方法的实现机制。"
        }
        """
    )

    assert parsed.template_relation == "detailed_method_summary"
    assert parsed.adjudications[0].satisfied is True
    assert parsed.adjudications[1].satisfied is False


def test_adjudication_prompt_separates_method_summary_from_positive_evaluation():
    prompt = build_template_direct_adjudication_prompt(
        citing_paper_title="LD-Recognition",
        cited_paper_title=TARGET_TITLE,
        target_reference_marker="[26]",
        target_reference_entry=TARGET_ENTRY,
        evidence=_postprocess(_method_evidence()),
        template_prompt_fragments=["method template"],
    )

    assert "does not require praise" in prompt
    assert "Do not relabel a factual method summary" in prompt
    assert "Wang et al. [26]" in prompt


def test_missing_first_stage_template_ids_are_rejudged_per_evidence():
    service = ScholarFulltextService(None)
    evidence = _postprocess(_method_evidence())
    provider = AdjudicatingProvider(
        {
            "template_relation": "detailed_method_summary",
            "adjudications": [
                {
                    "template_id": 7,
                    "satisfied": True,
                    "confidence": "high",
                    "reason": "The quote gives concrete features and algorithms.",
                }
            ],
            "why_this_judgment_zh": "正文说明了两个物理层特征及后续算法。",
            "copy_ready_zh": "后续论文具体概述了目标方法的特征提取与匹配机制。",
        }
    )
    item = SimpleNamespace(
        citing_paper_title="LD-Recognition",
        cited_paper_title=TARGET_TITLE,
    )

    payload = service._adjudicate_direct_evidences(
        item=item,
        provider=provider,
        payload={
            "target_reference_marker": "[26]",
            "target_reference_entry": TARGET_ENTRY,
            "evidences": [evidence],
        },
        active_templates=[_template()],
    )
    payload = service._apply_active_templates_to_direct_payload(
        item=item,
        payload=payload,
        active_templates=[_template()],
    )
    result = payload["evidences"][0]

    assert len(provider.requests) == 1
    assert result["matched_template_ids"] == [7]
    assert result["template_relation"] == "detailed_method_summary"
    assert result["final_claim_type"] == "method_summary"
    assert result["final_recommendation"] == "include"


def test_hard_grounding_failure_skips_model_adjudication():
    service = ScholarFulltextService(None)
    evidence = _postprocess(
        {
            **_method_evidence(),
            "evidence_quote": "Indoor localization [3], [4], [5] is common.",
        }
    )
    provider = AdjudicatingProvider(
        {
            "template_relation": "detailed_method_summary",
            "adjudications": [],
        }
    )

    payload = service._adjudicate_direct_evidences(
        item=SimpleNamespace(
            citing_paper_title="Survey",
            cited_paper_title=TARGET_TITLE,
        ),
        provider=provider,
        payload={"evidences": [evidence]},
        active_templates=[_template()],
    )

    assert provider.requests == []
    assert payload["evidences"][0]["template_satisfied"] is False
    assert payload["evidences"][0]["final_recommendation"] == "exclude"

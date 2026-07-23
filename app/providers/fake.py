"""Fake providers for offline development and tests."""

import json
from typing import List

from app.providers.base import AuthorProvider, CitationProvider, LlmProvider, MetadataProvider
from app.schemas.llm import (
    CitationAnalysisResponse,
    LlmCitationAnalysisRequest,
    TemplateDirectAnalysisResult,
)
from app.schemas.provider import ProviderAuthorIdentity, ProviderCitationEdge, ProviderHealth, ProviderPublication


class FakeAuthorProvider(AuthorProvider):
    provider_name = "fake-author"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="Fake author provider is ready.",
        )

    def resolve_author(self, author_ref: str) -> ProviderAuthorIdentity:
        display_name = (author_ref or "").strip() or "Fake Scholar"
        return ProviderAuthorIdentity(
            display_name=display_name,
            dblp_id="pid/fake/Scholar",
            openalex_id="https://openalex.org/A000000001",
            scopus_author_id="00000000001",
            publications=[
                ProviderPublication(
                    title="Fake Scholar Publication on Evidence-Aware Impact",
                    year=2024,
                    venue="Journal of Scholarly Systems",
                    doi="10.0000/fake.scholar.001",
                    authors=[display_name, "Avery Stone"],
                    source_url="fake://scholar/publications/001",
                ),
                ProviderPublication(
                    title="Fake Scholar Publication on Citation Contexts",
                    year=2023,
                    venue="Proceedings of Research Analytics",
                    doi="10.0000/fake.scholar.002",
                    authors=[display_name],
                    source_url="fake://scholar/publications/002",
                ),
                ProviderPublication(
                    title="Fake Scholar Publication on Human Review Loops",
                    year=2022,
                    venue="Academic Workflow Review",
                    doi="10.0000/fake.scholar.003",
                    authors=[display_name, "Morgan Lee"],
                    source_url="fake://scholar/publications/003",
                ),
                ProviderPublication(
                    title="Fake Scholar Publication on Reportable Evidence",
                    year=2021,
                    venue="Digital Libraries Notes",
                    doi="10.0000/fake.scholar.004",
                    authors=[display_name, "Jordan Kim"],
                    source_url="fake://scholar/publications/004",
                ),
            ],
        )


class FakeCitationProvider(CitationProvider):
    provider_name = "fake"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="Fake provider is ready.",
        )

    def discover_citations(self, target_title: str) -> List[ProviderCitationEdge]:
        return [
            ProviderCitationEdge(
                target_title=target_title,
                citing_paper=ProviderPublication(
                    title="Evidence-Aware Academic Impact Assessment",
                    year=2024,
                    venue="Journal of Scholarly Metrics",
                    doi="10.0000/fake.impact.001",
                    authors=["Lin Chen", "Maya Patel"],
                    source_url="fake://citations/001",
                    citation_contexts=[
                        "This work builds on the target paper to evaluate evidence quality."
                    ],
                ),
            ),
            ProviderCitationEdge(
                target_title=target_title,
                citing_paper=ProviderPublication(
                    title="Citation Contexts for Research Evaluation",
                    year=2023,
                    venue="Proceedings of Research Analytics",
                    doi="10.0000/fake.impact.002",
                    authors=["Noah Smith"],
                    source_url="fake://citations/002",
                    citation_contexts=[
                        "The target paper is cited as an example of context-aware assessment."
                    ],
                ),
            ),
            ProviderCitationEdge(
                target_title=target_title,
                citing_paper=ProviderPublication(
                    title="Human Review Loops in Scholarly Analytics",
                    year=2025,
                    venue="Academic Systems Review",
                    doi="10.0000/fake.impact.003",
                    authors=["Aisha Kumar", "Jonas Weber"],
                    source_url="fake://citations/003",
                    citation_contexts=[
                        "The authors compare their review workflow with the target paper."
                    ],
                ),
            ),
            ProviderCitationEdge(
                target_title=target_title,
                citing_paper=ProviderPublication(
                    title="Template-Based Evidence Classification",
                    year=2022,
                    venue="Digital Libraries Forum",
                    doi="10.0000/fake.impact.004",
                    authors=["Elena Rossi"],
                    source_url="fake://citations/004",
                    citation_contexts=[
                        "The target paper motivates a reusable evidence classification template."
                    ],
                ),
            ),
            ProviderCitationEdge(
                target_title=target_title,
                citing_paper=ProviderPublication(
                    title="PDF Grounding for Citation Analysis",
                    year=2024,
                    venue="Information Retrieval Notes",
                    doi="10.0000/fake.impact.005",
                    authors=["Owen Garcia", "Sara Novak"],
                    source_url="fake://citations/005",
                    citation_contexts=[],
                ),
            ),
        ]


class FakeMetadataProvider(MetadataProvider):
    provider_name = "fake-metadata"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="Fake metadata provider is ready.",
        )

    def resolve_publication(self, query: str):
        return ProviderPublication(
            title=(query or "").strip() or "Fake Metadata Publication",
            year=2024,
            venue="Fake Metadata Venue",
            doi=None,
            authors=["Fake Author"],
            source_url="fake://metadata/publication",
        )


class FakeLlmProvider(LlmProvider):
    provider_name = "fake-llm"

    def __init__(self) -> None:
        self.last_raw_response_text = ""
        self.last_normalized_response = {}

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            ok=True,
            message="Fake LLM provider is ready.",
        )

    def analyze_text(self, prompt: str) -> str:
        return self.analyze_citation(
            LlmCitationAnalysisRequest(
                target_title="",
                candidate_spans=[self._first_candidate_span(prompt)],
            )
        ).model_dump_json()

    def analyze_citation(self, request: LlmCitationAnalysisRequest) -> CitationAnalysisResponse:
        if request.analysis_scope == "fulltext_template_direct":
            return self._template_direct_response(request)
        candidate_text = request.candidate_spans[0] if request.candidate_spans else ""
        if (
            not candidate_text
            and request.analysis_scope in {"fulltext_direct", "fulltext_anchor_direct"}
            and request.full_text
        ):
            candidate_text = self._fulltext_direct_evidence_text(request)
        findings = []
        if candidate_text:
            findings.append(
                {
                    "evidence_type": "method_foundation",
                    "stance": "positive",
                    "mention_type": "strong",
                    "citation_text": candidate_text,
                    "reasoning": "The citing text makes a concrete methodological dependency claim.",
                    "keywords": ["method foundation", "citation evidence", "target paper"],
                }
            )
            findings.append(
                {
                    "evidence_type": "important_author_citation",
                    "stance": "neutral",
                    "mention_type": "grouped_citation",
                    "citation_text": "Several related systems are cited together [1, 2, 3].",
                    "reasoning": "Grouped citation is not specific enough for strong evidence.",
                    "keywords": ["related systems"],
                }
            )
            findings.append(
                {
                    "evidence_type": "application_extension",
                    "stance": "positive",
                    "mention_type": "strong",
                    "citation_text": None,
                    "reasoning": "No original citation text was provided for this finding.",
                    "keywords": ["application"],
                }
            )

        payload = {"findings": findings}
        self.last_raw_response_text = json.dumps(payload, ensure_ascii=False)
        self.last_normalized_response = payload
        return CitationAnalysisResponse.model_validate(payload)

    def _template_direct_response(self, request: LlmCitationAnalysisRequest):
        quote = self._fulltext_direct_evidence_text(request)
        reference_entry = f"[1] Fake reference entry for {request.cited_paper_title or request.target_title}."
        payload = {
            "target_reference_marker": "[1]",
            "target_reference_entry": reference_entry,
            "paper_level_summary_zh": "引用论文在正文中讨论了目标论文，以下证据需以原文锚点为准。",
            "evidences": [
                {
                    "recommendation": "include" if quote else "review",
                    "claim_type": "method_use" if quote else "ordinary_reference",
                    "evidence_quote": quote,
                    "evidence_context": request.full_text[:1200] if request.full_text else quote,
                    "reference_entry": reference_entry,
                    "why_this_judgment_zh": "该判断来自全文直接分析结果，证据句来自正文并与目标论文引用锚点相关。",
                    "copy_ready_zh": "引用论文在正文中使用或讨论了目标论文，可作为报告候选证据；正式使用前应核对原文上下文。",
                    "confidence": "medium",
                }
            ] if quote else [],
        }
        self.last_raw_response_text = json.dumps(payload, ensure_ascii=False)
        self.last_normalized_response = payload
        return TemplateDirectAnalysisResult.model_validate(payload)

    def _fulltext_direct_evidence_text(self, request: LlmCitationAnalysisRequest) -> str:
        target_title = (request.cited_paper_title or request.target_title or "").lower()
        sentences = [
            sentence.strip()
            for sentence in request.full_text.replace("\n", " ").split(".")
            if sentence.strip()
        ]
        for sentence in sentences:
            if target_title and target_title in sentence.lower():
                return sentence + "."
        return sentences[0] + "." if sentences else ""

    def _first_candidate_span(self, prompt: str) -> str:
        for line in prompt.splitlines():
            if line.startswith("- "):
                return line[2:].strip()
        return ""

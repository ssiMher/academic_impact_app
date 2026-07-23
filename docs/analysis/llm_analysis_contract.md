# LLM Analysis Contract

## Current Phase 13 Scope

The citation analysis flow supports both ordinary paper analysis and scholar
queue analysis. `FakeLlmProvider` remains the default for local development and
automated tests. `OpenAICompatibleLlmProvider` can be enabled by configuration
for manual real-LLM analysis.

Supported scopes:

- `candidate_spans`: deterministic candidate span selection, faster but may
  miss the relevant citation context in long papers.
- `fulltext_direct`: sends the full extracted citing paper text to the LLM,
  slower and limited by `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`.

Supported `candidate_spans` flow:

1. Use extracted citing-paper text from `PdfAsset.extracted_text_path`.
2. Build a target citation anchor from `PaperAnalysisSession.query_text` or the
   scholar queue item's cited publication title.
3. Locate candidate spans with local deterministic logic.
4. Build a prompt for analysis.
5. Build `LlmCitationAnalysisRequest`.
6. Call the configured `LlmProvider`.
7. Validate the provider output with Pydantic into `CitationAnalysisResponse`.
8. Persist `FulltextAnalysisResult`.
9. Convert eligible findings into `StrongEvidence`.

For scholar queue analysis, the persisted rows are linked through
`scholar_session_id`, `queue_item_id`, and `citation_edge_id`.

## Candidate Spans

`candidate_spans` are selected locally from extracted text. The current implementation matches the normalized target title or enough target-title keywords. This is intentionally simple and deterministic so tests can validate behavior without network or model variance.

## Fulltext Direct

`fulltext_direct` reads the full extracted text from `PdfAsset.extracted_text_path`
and builds an LLM prompt containing the citing paper title, cited paper title,
available cited-paper metadata, active template fragments, an optional target
reference marker such as `[15]`, the matching reference entry, and full
extracted text.

The prompt requires the model to:

- analyze the citing paper full text;
- determine whether and how it cites or discusses the cited paper;
- report only evidence explicitly grounded in the supplied text;
- include `citation_text` copied from the full text for every finding;
- return `findings=[]` when the text only shares similar keywords but does not
  clearly discuss the cited paper;
- avoid inventing evidence or inferring praise without textual support;
- avoid attributing grouped-citation claims to the cited paper unless the text
  clearly applies to it.
- output only JSON with top-level `{"findings": [...]}` and the required
  finding fields: `citation_text`, `evidence_type`, `stance`, `mention_type`,
  `reasoning`, `highlight_keywords`, and `keep`.
- avoid bibliography/reference-list entries. A reference entry only proves the
  cited paper appears in References and must not become evidence of evaluation,
  use, comparison, or contribution.
- use `citation_text` from main-body discussion. If the only occurrence of the
  cited paper is in References, the provider should return `{"findings":[]}`.
- if a grouped citation contains the target reference marker, the provider may
  return `mention_type=grouped_citation` and should explain attribution
  uncertainty rather than dropping the finding.

If the full extracted text exceeds `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`,
analysis fails with `fulltext_too_long_for_direct_analysis`. The system must not
silently truncate full text in this mode.

When `ACADEMIC_IMPACT_DEBUG_SAVE_LLM_PROMPTS=true`, each analysis result may
save `prompt.txt`, `raw_response.txt`, `normalized_response.json`, and
`metadata.json`. Saved metadata may include task id, scholar session id, queue
item id, fulltext result id, analysis scope, provider, model, prompt version,
and prompt/response character counts. API keys, request headers, authorization
tokens, and local absolute paths must not be saved.

## Provider Selection

Configuration keys:

| Key | Purpose |
| --- | --- |
| `ACADEMIC_IMPACT_LLM_PROVIDER` | `fake` or `openai_compatible`; defaults to `fake` |
| `ACADEMIC_IMPACT_LLM_BASE_URL` | OpenAI-compatible API base URL |
| `ACADEMIC_IMPACT_LLM_API_KEY` | Runtime API key; never logged or persisted |
| `ACADEMIC_IMPACT_LLM_MODEL` | Chat completion model name |
| `ACADEMIC_IMPACT_LLM_TIMEOUT_SECONDS` | Provider request timeout |
| `ACADEMIC_IMPACT_LLM_DISABLE_THINKING` | Optional provider hint to disable thinking mode |
| `ACADEMIC_IMPACT_DEBUG_SAVE_LLM_PROMPTS` | Save prompt/response debug artifacts when `true` |
| `ACADEMIC_IMPACT_DEBUG_LLM_DIR` | Root directory for saved prompt/response debug artifacts |

Tests must use fake providers or HTTP monkeypatching. They must not call real LLM services.

## Fake LLM Contract

`FakeLlmProvider` returns objects matching `app.schemas.llm.CitationAnalysisResponse`. It is deterministic and must remain the default test provider.

## OpenAI-Compatible Contract

`OpenAICompatibleLlmProvider` uses the `chat/completions` endpoint and sends a redacted-log-safe request derived from `LlmCitationAnalysisRequest`.

Provider output must be JSON matching `CitationAnalysisResponse`. Plain JSON and fenced JSON are accepted. Invalid JSON or schema mismatch maps to `provider_schema_error`.
The parser also strips `<think>...</think>` blocks, extracts the first embedded
JSON object from surrounding natural language, normalizes top-level
`{"evidence": [...]}` to `{"findings": [...]}`, and treats explicit no-evidence
text such as `no evidence found` as `{"findings": []}`.
Finding field aliases are normalized before validation:

- `evidence_type`, `aspect`, `type`, or `category`
- `citation_text`, `quote`, `evidence_quote`, or `text`
- `reasoning`, `reason`, or `evidence_reason`
- `keywords` or `highlight_keywords`

For scholar `fulltext_direct`, schema-mismatched findings are repaired only when
the quote itself supports the missing labels. Reference-list entries and generic
similar-keyword sentences that cannot be attributed to the cited paper are
removed. If no valid findings remain, the persisted result is
`{"findings":[]}` rather than a schema failure.

Provider error mapping:

| Provider condition | Internal error code |
| --- | --- |
| Timeout | `timeout` |
| HTTP 401 or 403 | `auth_error` |
| HTTP 429 | `rate_limit` |
| HTTP 5xx | `transient_provider_error` |
| Invalid JSON or schema mismatch | `provider_schema_error` |

Each finding must use one of the built-in evidence types:

- `first_or_seminal_claim`
- `detailed_comparison`
- `baseline_or_benchmark`
- `method_foundation`
- `theoretical_foundation`
- `application_extension`
- `positive_evaluation`
- `limitation_or_negative`
- `background`
- `adopted_or_combined`
- `state_of_the_art_claim`
- `important_author_citation`
- `long_context_citation`

Findings without original `citation_text` are persisted only inside `FulltextAnalysisResult.parsed_result_json`; they must not create `StrongEvidence`.

Grouped citations are scored weakly by local deterministic scoring. Most remain
filtered, but some high-value grouped findings with explicit quote text may be
saved as low/medium strength evidence with `anchor_status=grouped_citation` and
an evidence note explaining that manual attribution review is required.

## Error Handling

- Missing PDF or missing extracted text blocks analysis with a clear `need_pdf` or `need_extracted_text` state at the page/API layer.
- If an `analyze_citation` task runs without usable extracted text, it fails and records `AnalysisTask.error_message`.
- If provider output is invalid JSON or fails Pydantic validation, the task fails and records `AnalysisTask.error_message`.
- For scholar `fulltext_direct`, provider schema errors also create a failed
  `FulltextAnalysisResult` with safe diagnostics in `parsed_result_json`,
  including `provider_schema_error`, `raw_output_preview`, `parse_error`, and
  `schema_error` when available.
- For scholar `fulltext_direct`, schema errors caused by repairable missing
  finding fields are normalized conservatively before failure is recorded.
  Repair never invents evidence, never promotes reference-list entries, and
  never creates `StrongEvidence` without main-body `citation_text`.
- API keys must not be logged, rendered in health pages, stored in SQLite, or persisted in provider request logs.

## Export Contract

Phase 8.5 exports read existing analysis results only. Export generation must not call the configured LLM provider, re-run candidate span detection, re-run PDF extraction, or access real external APIs.

`report.md` includes session summary, citing paper counts, analyzed citing paper counts, strong evidence counts, citing paper PDF status such as `need_pdf`, and evidence fields: citing paper title, aspect, stance, mention type, evidence strength, score, citation text, highlight keywords, and reason.

`structured.json` includes:

- `exports`: metadata with schema version, generation timestamp, and supported formats.
- `session`: paper analysis session summary.
- `citing_papers`: citing paper summaries and publication metadata.
- `fulltext_results`: stored fulltext analysis results.
- `strong_evidence`: exportable evidence with reason resolved from the stored parsed result.

Export output must not include local absolute paths, `PdfAsset.storage_path`, `PdfAsset.extracted_text_path`, API keys, provider raw secrets, or provider request logs.

## Scholar Queue Analysis Contract

Phase 13 analyzes only selected queue items whose PDF readiness is
`manual_pdf` or `local_library_pdf`. `need_pdf` items are skipped with a clear
warning and do not crash the whole task batch.

Scholar analysis uses the queue item's cited publication as the target paper and
the queue item's citing publication as the citing paper. The prompt must include
the target citation anchor and candidate spans from extracted text.

For `fulltext_direct`, `FulltextAnalysisResult.analysis_scope` is
`fulltext_direct` and `candidate_spans_json` stores diagnostics such as
`mode`, `fulltext_chars`, and `llm_findings_count` instead of candidate spans.
If provider schema validation fails, the evidence page displays the failed
result id, scope, full text character count, status, error message, raw output
preview, and schema error so users can distinguish parser failures from genuine
empty evidence.

If `llm_findings_count > 0` but no evidence is saved, diagnostics must expose:

- per-finding citation preview
- evidence type / stance / mention type
- filter reason
- model reasoning
- filter reason distribution

This allows the user to distinguish valid filtering (`background_neutral`,
`reference_only`, `reference_entry`, `grouped_citation_too_ambiguous`,
`grouped_citation_saved_for_review`, `low_strength`, `no_citation_text`,
`no_body_anchor`) from prompt or parser problems.

Repeated analysis may create a new `FulltextAnalysisResult`, but it must not
create duplicate `StrongEvidence` for the same queue item, citation edge,
aspect, stance, mention type, and citation text. Existing evidence review
status and user notes must be preserved.

## Provider Boundary

The LLM provider abstraction must preserve this contract across ordinary paper
analysis and scholar queue analysis:

- No raw provider response leaks into business-facing schemas.
- Local scoring remains responsible for promotion and ordering.
- Findings without original citation text do not create `StrongEvidence`.
- Tests must not call real network services.
- Real scholarly metadata providers, automatic PDF download, highlight cards,
  final scholar reports, and Redis/Celery remain out of scope.

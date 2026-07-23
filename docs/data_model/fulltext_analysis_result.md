# FulltextAnalysisResult Data Model

`FulltextAnalysisResult` stores one structured full-text analysis run. It now
supports both ordinary paper analysis and scholar queue analysis.

| Field | Purpose |
| --- | --- |
| `id` | Primary key |
| `paper_session_id` | Optional parent `PaperAnalysisSession` for ordinary paper analysis |
| `scholar_session_id` | Optional parent `ScholarAnalysisSession` for scholar queue analysis |
| `citing_paper_id` | Optional `CitingPaper` for ordinary paper analysis |
| `queue_item_id` | Optional `DeepAnalysisQueueItem` for scholar analysis |
| `citation_edge_id` | Optional source `CitationEdge` for scholar analysis |
| `analysis_scope` | Analysis mode, such as `citation_context`, `candidate_spans`, or `fulltext_direct` |
| `status` | `pending`, `succeeded`, or `failed` |
| `llm_provider` | Provider name used for the run, e.g. `fake-llm` |
| `llm_model` | Configured model name, when applicable |
| `prompt_version` | Prompt/pipeline version label |
| `candidate_spans_json` | Candidate spans selected before LLM analysis, or diagnostics for `fulltext_direct` |
| `parsed_result_json` | Pydantic-validated `CitationAnalysisResponse` JSON, or safe failure diagnostics |
| `error_message` | Clear error text for failed analysis |
| `created_at`, `updated_at` | Local timestamps |

## Phase 13 Rules

- Scholar queue analysis must set `scholar_session_id`, `queue_item_id`, and
  `citation_edge_id`.
- Ordinary paper analysis may continue to set only `citing_paper_id`.
- The table stores extracted findings and metadata, not PDF binaries or large
  full-text blobs.
- Provider secrets and raw provider request logs must not be stored here.

## Fulltext Direct Diagnostics

When `analysis_scope = fulltext_direct`, `candidate_spans_json` may store a
diagnostic object instead of candidate spans:

```json
{"mode": "fulltext_direct", "fulltext_chars": 12345, "llm_findings_count": 0}
```

The full extracted text is sent to the provider prompt but is not stored in this
table. If the text exceeds `ACADEMIC_IMPACT_FULLTEXT_DIRECT_MAX_CHARS`, no
`FulltextAnalysisResult` is created for that item.

If the provider returns JSON findings with missing required fields, the
`fulltext_direct` path may store a conservatively repaired
`CitationAnalysisResponse`. Repair removes reference-list entries and
unattributed generic sentences. If repair cannot produce valid schema output,
`status = failed` and `parsed_result_json` stores safe diagnostics such as
`provider_schema_error`, `raw_output_preview`, and `schema_error`; API keys and
request headers are never stored.

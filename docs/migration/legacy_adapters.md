# Legacy Adapter Migration

Phase 9 and 9.5 migrate only stable, testable, pure-function behavior from the old `academic_impact_web` project. The new project must keep its own modular architecture; old Web, service, task, and session-state flows are not imported.

## Migrated Adapters

| Adapter | Migrated capability | Output boundary |
| --- | --- | --- |
| `app/legacy/adapters/pdf_extract_adapter.py` | PDF text extraction and extraction-error classification | `LegacyPdfExtractResult`, `LegacyPdfPage`, `LegacyPdfExtractError` dataclasses |
| `app/legacy/adapters/candidate_spans_adapter.py` | Candidate citation span location with reference-section exclusion | `LegacyCandidateSpanResult`, `LegacyCandidateSpan`, `LegacyFulltextPage` dataclasses |
| `app/legacy/adapters/llm_json_parser_adapter.py` | Direct JSON, fenced JSON, embedded JSON, and `<think>` block stripping | New-project `CitationAnalysisResponse` schema |
| `app/legacy/adapters/dblp_normalize_adapter.py` | DBLP record id normalization | Plain normalized DBLP id string |
| `app/legacy/adapters/local_pdf_match_adapter.py` | Local PDF matching by title, DOI, and arXiv id | `LocalPdfMatch` dataclass |
| `app/legacy/adapters/evidence_normalize_adapter.py` | Legacy evidence label, mention type, confidence, and highlight keyword normalization | `NormalizedLegacyFinding` dataclass and normalized strings/lists |

Regression inputs live under `tests/fixtures/legacy/`:

- `candidate_span_case.json`
- `llm_response_cases.json`
- `pdf_extract_case.json`
- `evidence_normalization_case.json`

## Forbidden Legacy Modules

Do not migrate or import these old-project flows into the new app:

- Old `app/main.py`
- Old `app/services/impact_core.py`
- Old `scholar_core.py`
- Old `run_pipeline.py`
- Old `session.json` as primary application state
- Old Web response, background task, or large CLI pipeline structures

If a useful function is buried inside one of those files, extract only the pure algorithm into an adapter and cover it with tests. Do not import the old module at runtime.

## Calling Boundary

Allowed:

- `analysis`, `pdf`, `providers`, and `services` may call `app/legacy/adapters/*` through clear function interfaces.
- Tests may import adapters directly.
- Adapters may use new-project schemas or dataclasses for their public output.

Not allowed:

- `routers` must not import `app/legacy/adapters`.
- Adapters must not read or write the database.
- Adapters must not perform real network requests.
- Adapters must not operate on FastAPI responses or templates.
- Adapters must not expose old-project dict structures such as `session.json` state.
- Adapters must not depend on user-machine absolute paths.

## Migration Rules

When migrating another old function:

1. Add or extend tests first.
2. Add a regression fixture under `tests/fixtures/legacy/` when behavior is non-trivial.
3. Copy or rewrite only the pure function logic needed for the adapter.
4. Return new-project dataclasses or schemas, not raw old-project dictionaries.
5. Keep network, environment-variable, file-system, Web, database, and task orchestration outside the adapter unless the adapter is explicitly a local-file adapter.
6. Run full `pytest`, including Phase 8 export integration tests.
7. Update this document and `docs/requirements_traceability.md` if the migrated capability expands.

## Verification

Phase 9.5 verification includes:

- Unit tests for every adapter.
- Golden regression fixture tests.
- Phase 8.5 full paper-analysis-to-export integration test.
- Boundary tests ensuring new services do not import old core/pipeline modules.
- Boundary tests ensuring routers do not import legacy adapters.
- Boundary tests ensuring adapters do not access the database, real network, or Web response objects.

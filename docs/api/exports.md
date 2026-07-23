# Export API

Phase 8.5 supports ordinary paper analysis exports for a `PaperAnalysisSession`.

## Routes

| Method | Path | Response |
| --- | --- | --- |
| `GET` | `/paper-sessions/{session_id}/exports/report.md` | UTF-8 Markdown attachment named `report.md` |
| `GET` | `/paper-sessions/{session_id}/exports/structured.json` | JSON attachment named `structured.json` |

If the session does not exist, export routes return `404`. Unsupported export paths, such as `/paper-sessions/{session_id}/exports/report.pdf`, are not routed and return `404`.

## `report.md`

The Markdown report includes:

- Session query, query kind, and session status.
- Citing paper count.
- Analyzed citing paper count.
- Strong evidence count.
- Citing paper list with title, analysis status, and PDF status such as `need_pdf`.
- Strong evidence list with citing paper title, aspect, stance, mention type, evidence strength, score, citation text, highlight keywords, and reason.

Empty states are valid:

- No citing papers: the report says no citing papers have been discovered.
- No strong evidence: the report says no strong evidence has been generated.
- Missing PDF: the citing paper entry shows `PDF status: need_pdf`.

## `structured.json`

The structured export contains:

| Field | Description |
| --- | --- |
| `exports` | Export metadata, including schema version, generation timestamp, and supported formats |
| `session` | Session summary |
| `citing_papers` | Citing paper summaries and publication metadata |
| `fulltext_results` | Existing fulltext analysis result payloads |
| `strong_evidence` | Exportable evidence rows enriched with citing paper title and reason |

The current export schema version is `phase8.5`.

## Safety Boundaries

- Export routes do not call LLM providers.
- Export routes do not re-run PDF extraction or citation analysis.
- Export routes do not access real external APIs.
- Export output must not include local absolute paths, `PdfAsset.storage_path`, `PdfAsset.extracted_text_path`, API keys, provider raw secrets, or provider request logs.

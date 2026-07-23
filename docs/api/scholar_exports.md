# Scholar Exports API

Phase 14 adds scholar-session exports built from existing `StrongEvidence` and
`HighlightCard` rows.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/scholar-sessions/{session_id}/exports/report.md` | Download scholar impact report markdown |
| `GET` | `/scholar-sessions/{session_id}/exports/report.pptx` | Download initial PPTX deck built from report-ready cards |
| `GET` | `/scholar-sessions/{session_id}/exports/structured.json` | Download structured scholar export |
| `GET` | `/scholar-sessions/{session_id}/exports/highlight_cards.csv` | Download highlight cards CSV |
| `GET` | `/scholar-sessions/{session_id}/exports/highlight_cards.md` | Download highlight cards markdown |

## Export Rules

- Reports only use existing evidence and cards.
- Rejected and false-positive evidence are excluded from report candidates.
- Cards whose source evidence is later rejected or marked false positive are
  excluded from default report output.
- PPTX output is an initial export surface. It must still preserve original
  evidence quotes and must not invent unsupported claims.
- Each card includes original `evidence_quote` and source citing paper title.
- Exports do not include `PdfAsset.storage_path`, extracted text paths, API
  keys, provider request payloads, or local absolute paths.

## Structured JSON Sections

- `exports`
- `scholar_session`
- `publications_summary`
- `citation_edges_summary`
- `queue_summary`
- `evidence_summary`
- `strong_evidence`
- `highlight_cards`

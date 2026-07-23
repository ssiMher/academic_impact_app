# Highlight Cards API

Phase 14 generates editable highlight cards from existing `StrongEvidence`.
Cards are deterministic drafts, not LLM-generated claims.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/scholar-sessions/{session_id}/cards` | Show card list with optional `card_type` filter |
| `GET` | `/scholar-sessions/{session_id}/report-workspace` | Show report workspace with editable narrative cards |
| `POST` | `/scholar-sessions/{session_id}/cards/generate` | Generate or refresh cards from eligible evidence |
| `POST` | `/scholar-sessions/{session_id}/evidence/{evidence_id}/generate-card` | Generate one card from one `StrongEvidence` row |
| `POST` | `/scholar-sessions/{session_id}/cards/{card_id}/edit` | Edit card title, body, note, and report inclusion flag |

## Generation Rules

- Every card must link to one `StrongEvidence`.
- Every card must carry an original evidence quote.
- Negative evidence generates `limitation_or_negative` cards and must stay in an
  objective feedback narrative.
- `accepted` and `important` evidence is preferred.
- Rejected and false-positive evidence does not generate cards.
- Unreviewed high-strength evidence can generate draft cards.
- Unknown important authors must stay `unknown`; the system must not invent
  fellow identity.
- Draft cards are marked in the subtitle.
- Re-generation must not overwrite user-edited title/body/note fields or
  arbitrarily change the edited card's sort order.

## Page Fields

The cards/report workspace page displays card type, source citing/cited paper
titles, evidence quote, highlighted quote HTML, score, strength, Chinese
narrative, notable-author metadata, grouped-citation warnings, user note, and
export links.

## Boundaries

- No LLM calls.
- No automatic PDF download.
- No card without original evidence quote.
- No local absolute path or API key rendering.

# PDF Inbox API

The PDF inbox supports browser-assisted restricted PDF download workflows. It
does not store publisher credentials, browser cookies, or session tokens.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/pdf-inbox` | Show scanned inbox PDFs and candidate queue matches |
| `POST` | `/pdf-inbox/rescan` | Enqueue `scan_pdf_inbox` task |
| `POST` | `/pdf-inbox/scan-now` | Run an immediate local inbox scan |
| `POST` | `/pdf-inbox/{entry_id}/bind` | Bind a candidate inbox PDF to a queue item |
| `POST` | `/pdf-inbox/{entry_id}/ignore` | Ignore an inbox PDF |

The scanner reads `ACADEMIC_IMPACT_PDF_INBOX_DIR`, creates or reuses
`PdfAsset` rows with `source_type=manual_download_inbox`, extracts text, and
matches against scholar queue items by DOI, normalized title, fuzzy title, and
title/year signals.

High-confidence matches are automatically bound. Medium-confidence matches are
shown for manual confirmation. Low-confidence files remain unmatched.

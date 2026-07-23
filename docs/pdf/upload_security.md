# PDF Upload Security

PDF uploads are accepted only when a user explicitly provides a file. The system
does not automatically download PDFs, does not use browser automation, and does
not scan directories outside configured local library paths.

## Validation

All upload routes must reuse the shared `PdfService` validation and storage
flow. Current checks include:

- reject empty files;
- allow only `.pdf` filenames;
- enforce the configured maximum upload size;
- verify PDF magic bytes;
- calculate `sha256`;
- store the PDF under the configured asset directory using an internal storage
  name, not the user-provided filename.

The database stores `PdfAsset` metadata only. It must not store PDF binary
content.

## Scholar Queue Upload

`DeepAnalysisQueueItem` with `pdf_readiness_status = need_pdf` can be made ready
by uploading the citing paper PDF from the queue page.

After a successful upload:

- a `PdfAsset` is created with `source_type = upload`;
- text extraction runs through the existing PDF extraction flow;
- the queue item stores the asset id in `pdf_asset_id`;
- the queue item status becomes `manual_pdf`.

If a queue item already has a `manual_pdf`, this phase refuses replacement with
a clear `409` error. A future explicit replace flow must preserve auditability
and avoid accidental loss of a user-selected PDF.

## Manual vs Local Library PDF

`manual_pdf` is a user-uploaded PDF and has priority over local-library matches.
`local_library_pdf` is matched from the configured Phase 11 local PDF index.
Local-library matching must not overwrite manual uploads.

## Display And Export Safety

Pages and exports may show the original filename and source type. They must not
show local absolute paths, storage paths, API keys, provider secrets, or raw
provider credentials.

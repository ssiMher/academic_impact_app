# Local PDF Library

The local PDF library is a configured scan source for the global PDF asset pool.
It is not a separate store. Manual uploads, local-directory imports, and reused
PDFs are all represented by `PdfAsset` rows, and publication identity bindings
are represented by `PdfAssetPublicationLink`.

The feature does not download PDFs, access institutional accounts, launch
browser automation, or scan paths submitted by users.

## Configuration

| Environment variable | Purpose |
| --- | --- |
| `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS` | Optional list of allowed local directories, separated by the platform path separator |
| `ACADEMIC_IMPACT_PDF_INDEX_PATH` | Metadata path recorded on each index run |
| `ACADEMIC_IMPACT_PDF_MAX_SCAN_FILES` | Maximum `.pdf` files scanned in one rebuild task |
| `ACADEMIC_IMPACT_PDF_MATCH_THRESHOLD` | Minimum score required before a local file becomes a `PdfAsset` match |

When `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS` is empty, the app keeps running and the
library page displays `local library disabled`.

## Indexing

Index rebuilds must run through `rebuild_pdf_index` tasks. Page requests only
enqueue work and never scan the whole library directly.

The scanner:

- Reads only configured directories.
- Looks for `.pdf` files.
- Skips symlinks and non-regular files.
- Stops at `ACADEMIC_IMPACT_PDF_MAX_SCAN_FILES`.
- Computes SHA-256 from file bytes.
- Extracts DOI, arXiv id, and title candidates from filenames.
- Stores metadata in `PdfLibraryIndex` and `PdfLibraryEntry`.
- Creates or reuses `PdfAsset` rows by SHA-256.
- Extracts text into `PdfAsset.extracted_text_path` when possible.
- Creates `PdfAssetPublicationLink` rows when DOI or normalized title can be
  matched to an existing `Publication`.

Rebuilds are repeatable. A successful rebuild replaces the current
`PdfLibraryEntry` view, so repeatedly indexing the same configured files does
not accumulate duplicate entry rows for the same file.

The implementation currently keeps local-library files in place and stores the
source path in `PdfAsset.storage_path` for worker use. It does not copy those
files into `var/pdf_assets/`. Pages and exports must hide the full path.

## Matching

Matching supports:

- DOI exact match with score `1.0`.
- arXiv id exact match with score `0.98`.
- Normalized title fuzzy match.

DOI exact match takes precedence over title fuzzy match. arXiv exact match takes
precedence over title fuzzy match when DOI does not match. Title-only matches
below `ACADEMIC_IMPACT_PDF_MATCH_THRESHOLD` are ignored.

If the score is at or above `ACADEMIC_IMPACT_PDF_MATCH_THRESHOLD`, the service
creates or reuses a `PdfAsset` with `source_type=local_library` and records a
publication link. It does not copy PDF bytes into the database.

Manual uploads are protected: if a `CitingPaper` or `ScholarPublication` already
has a `pdf_asset_id`, local library matching skips it and never overwrites it.

Queue reuse also checks previously uploaded PDFs via `PdfAssetPublicationLink`:

- DOI exact match: auto-attach as `reused_pdf`.
- OpenAlex ID exact match: auto-attach as `reused_pdf`.
- Publication id exact match: auto-attach as `reused_pdf`.
- Normalized title exact match: auto-attach as `reused_pdf`.
- Filename/title similarity between `0.80` and `0.95`: show as a candidate for
  manual confirmation.
- Similarity below `0.80`: ignore.

## Path Safety

Database entries keep the full `file_path` so workers can read local files later.
Pages and exports should display only filenames or redacted directory names, not
full local absolute paths.

The `/pdf-library` page shows two separate areas:

- PDF asset pool: uploaded/imported PDF count, extracted text count, linked
  publication count, queue reuse count, and recent assets.
- Local scan sources: configured source dirs, directory existence warnings,
  latest scan entry count, and rebuild controls.

If the scan index is empty but uploaded PDFs exist, the page must say that local
scan entries are empty while uploaded PDF assets are still available for queue
reuse.

The `/pdf-library` page and `/pdf-library.json` status endpoint return redacted
directory names and filenames only. Paper-session and scholar exports continue
to omit `PdfAsset.storage_path`, `PdfLibraryEntry.file_path`, and other local
absolute paths.

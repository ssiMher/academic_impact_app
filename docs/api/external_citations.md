# External Citation Import API

External citation import lets users upload citation lists exported from Google
Scholar-adjacent tools such as Publish or Perish, Zotero, or custom CSV files.
The application does not scrape Google Scholar pages and does not bypass
captchas.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/scholar-sessions/{session_id}/external-citations/import` | Show scholar-session CSV import form |
| `POST` | `/scholar-sessions/{session_id}/external-citations/import` | Import scholar-session external citation CSV |
| `GET` | `/paper-sessions/{session_id}/external-citations/import` | Show paper-session CSV import form |
| `POST` | `/paper-sessions/{session_id}/external-citations/import` | Import paper-session external citation CSV |

## Supported CSV Fields

The importer accepts canonical fields and Publish or Perish-style columns:

- `title` / `Title`
- `authors` / `Authors`
- `year` / `Year`
- `venue` / `Source` / `Publisher`
- `doi` / `DOI`
- `url` / `ArticleURL`
- `cited_by_url` / `CitesURL`
- `source`
- `gs_rank` / `GSRank`
- `cluster_id`

## Deduplication

Rows are matched against existing records by exact DOI, exact normalized title,
normalized-title similarity of at least `0.92`, and title/year compatibility.
Rows matching existing OpenAlex edges are recorded as matched rows instead of
creating duplicate citation edges.

External import counts are displayed separately from OpenAlex counts because
Google Scholar, Publish or Perish, and OpenAlex use different source coverage.

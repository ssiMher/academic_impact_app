# DBLP Author Provider

`DblpAuthorProvider` supports the author provider contract.

## Capabilities

- `health_check()`
- `search_authors(query, limit)`
- `resolve_author(author_ref)`
- `list_publications(author_identity)`

`author_ref` may be a DBLP pid, `pid/...` value, or DBLP author URL. The provider
normalizes values through the Phase 9 DBLP normalize adapter and strips the
author `pid/` prefix before requesting bibliography XML.

## Output Mapping

DBLP records are mapped to `ProviderPublication`:

- `title`
- `year`
- `venue` from journal or booktitle
- `doi` from DOI-style `ee` links
- `authors`
- `source_url`

## Boundaries

Automated tests monkeypatch HTTP and never call DBLP. Scopus, Elsevier,
institutional accounts, browser automation, and PDF download are out of scope.


# Queue Scoring

Phase 12 queue scoring is deterministic and local. It is not an academic
judgment and does not call LLMs.

## Initial Factors

| Factor | Effect |
| --- | --- |
| `third_party_status == third_party` | Adds `third_party_citation` |
| `self_citation_status == self_citation` | Adds `self_citation_penalty` |
| `self_citation_status == possible_self_citation` | Adds a smaller penalty |
| `pdf_readiness_status in manual_pdf/local_library_pdf` | Adds `pdf_ready` |
| `venue_tier == A/B/C` | Adds venue tier score |
| Recent citing paper year | Adds recency score |
| `user_review_status == important` | Adds highest user-priority boost |
| `user_review_status == rejected` or `queue_status == skipped` | Adds penalty |

Important user review status is intentionally the strongest boost so a human can
force a queue item to the top. Rejected items receive a large penalty. Skipped
items also receive a penalty and can be filtered out or inspected separately.

Every contribution is stored in `priority_reasons_json`, for example:

```json
[
  {"reason": "third_party_citation", "delta": 20},
  {"reason": "pdf_ready", "delta": 15},
  {"reason": "venue_tier_a", "delta": 10}
]
```

## Self-Citation Rule

Phase 12 uses a simple exact normalized-name overlap between citing authors and
cited paper authors. It marks obvious overlap as `self_citation`; missing author
data is `ambiguous`. It does not attempt complex author disambiguation.

## Sorting

Queue lists sort by:

1. `priority_score` descending.
2. `year` descending.
3. `venue_tier`.
4. `pdf_readiness_status`.

This ordering is deterministic enough for Phase 13 to consume selected queue
items without requiring fulltext analysis in Phase 12.5.

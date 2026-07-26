#!/usr/bin/env python3
"""Regenerate persisted evidence/cards from an existing direct result."""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.base import init_db
from app.db.session import SessionLocal
from app.services.template_direct_persistence_service import (
    TemplateDirectPersistenceService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or persist StrongEvidence and HighlightCard rows from an "
            "existing fulltext_template_direct result. No LLM is called."
        )
    )
    parser.add_argument("--fulltext-result-id", type=int, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write idempotent StrongEvidence/HighlightCard rows.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    init_db()
    db = SessionLocal()
    try:
        service = TemplateDirectPersistenceService(db)
        summary = (
            service.persist(args.fulltext_result_id)
            if args.apply
            else service.preview(args.fulltext_result_id)
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    finally:
        db.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

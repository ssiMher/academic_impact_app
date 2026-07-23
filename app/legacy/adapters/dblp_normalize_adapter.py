"""Adapter for DBLP record id normalization."""

import re
from urllib.parse import urlparse


def normalize_dblp_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    raw = re.sub(r"^dblp\s*:\s*", "", raw, flags=re.I).strip()
    parsed = urlparse(raw)
    if parsed.netloc:
        path = parsed.path.strip("/")
        if path.startswith("rec/"):
            path = path[len("rec/") :]
        raw = path

    raw = raw.strip().strip("/")
    raw = re.sub(r"\.(html|xml|bib)$", "", raw, flags=re.I)
    if raw.startswith("db/"):
        raw = raw[len("db/") :]
    raw = re.sub(r"/+", "/", raw)
    return raw

"""Filesystem storage helpers for uploaded PDFs."""

import hashlib
from pathlib import Path
from uuid import uuid4


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save_pdf_bytes(content: bytes, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    storage_path = directory / f"{uuid4().hex}.pdf"
    storage_path.write_bytes(content)
    return storage_path

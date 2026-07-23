"""Build normalized metadata for local PDF library entries."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.pdf.arxiv import extract_arxiv_identifier
from app.pdf.match import normalize_title_for_match


@dataclass(frozen=True)
class PdfFileMetadata:
    file_path: Path
    filename: str
    size_bytes: int
    sha256: str
    detected_doi: Optional[str]
    detected_arxiv_id: Optional[str]
    normalized_title: str
    title_candidates: List[str]


def extract_doi_from_filename(filename: str) -> Optional[str]:
    stem = Path(filename).stem
    match = re.search(r"(10\.\d{4,9})[._-]+([A-Za-z0-9][A-Za-z0-9._-]*)", stem)
    if not match:
        return None
    suffix = match.group(2).strip("._-")
    if not suffix:
        return None
    parts = suffix.split("_")
    doi_suffix = parts[0]
    if len(parts) > 1 and "." not in doi_suffix:
        doi_suffix = f"{doi_suffix}.{parts[1]}"
    return f"{match.group(1)}/{doi_suffix}".lower()


def extract_arxiv_id_from_filename(filename: str) -> Optional[str]:
    return extract_arxiv_identifier(filename, allow_bare=True)


def title_candidates_from_filename(filename: str) -> List[str]:
    stem = Path(filename).stem
    without_doi = re.sub(r"10\.\d{4,9}[._-]+[A-Za-z0-9._-]+", " ", stem)
    arxiv_id = extract_arxiv_identifier(filename, allow_bare=True)
    without_arxiv = without_doi
    if arxiv_id:
        without_arxiv = re.sub(
            rf"(?i)(?:arxiv[_\s-]*)?{re.escape(arxiv_id)}",
            " ",
            without_arxiv,
        )
    title = re.sub(r"[_-]+", " ", without_arxiv)
    title = " ".join(title.split())
    return [title] if title else []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata_from_pdf_path(path: Path) -> PdfFileMetadata:
    candidates = title_candidates_from_filename(path.name)
    normalized_title = normalize_title_for_match(candidates[0] if candidates else path.stem)
    return PdfFileMetadata(
        file_path=path,
        filename=path.name,
        size_bytes=path.stat().st_size,
        sha256=sha256_file(path),
        detected_doi=extract_doi_from_filename(path.name),
        detected_arxiv_id=extract_arxiv_id_from_filename(path.name),
        normalized_title=normalized_title,
        title_candidates=candidates,
    )

"""Safe local PDF library discovery."""

import os
from pathlib import Path
from typing import Iterable, List


def parse_library_dirs(raw_value: str) -> List[Path]:
    if not raw_value:
        return []
    return [Path(part).expanduser() for part in raw_value.split(os.pathsep) if part.strip()]


def redact_path(path: Path) -> str:
    return path.name


def scan_pdf_library(library_dirs: Iterable[Path], max_scan_files: int) -> List[Path]:
    pdf_paths: List[Path] = []
    for library_dir in library_dirs:
        if not library_dir.exists() or not library_dir.is_dir():
            continue
        for candidate in library_dir.rglob("*.pdf"):
            if len(pdf_paths) >= max_scan_files:
                return pdf_paths
            if candidate.is_symlink() or not candidate.is_file():
                continue
            pdf_paths.append(candidate)
    return pdf_paths

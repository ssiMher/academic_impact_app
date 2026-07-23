"""Adapter for legacy-style PDF text extraction."""

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from pypdf import PdfReader


MIN_EXTRACTED_TEXT_CHARS = 20


@dataclass(frozen=True)
class LegacyPdfPage:
    page: int
    text: str


@dataclass(frozen=True)
class LegacyPdfExtractError:
    error_type: str
    error_stage: str
    suggestion: str
    fallback_plan: str = ""


@dataclass(frozen=True)
class LegacyPdfExtractResult:
    ok: bool
    text: str = ""
    page_count: int = 0
    pages: List[LegacyPdfPage] = field(default_factory=list)
    extractor: str = "pypdf"
    error: str = ""
    error_type: str = ""
    error_stage: str = ""
    suggestion: str = ""


def classify_pdf_extract_error(exc: Exception) -> LegacyPdfExtractError:
    text = str(exc or "")
    lowered = text.lower()
    if "password" in lowered or "encrypted" in lowered:
        return LegacyPdfExtractError(
            error_type="pdf_encrypted",
            error_stage="extract_text_failed",
            suggestion="该 PDF 可能已加密，请先提供未加密版本。",
            fallback_plan="可尝试重新导出为未加密 PDF 后再上传。",
        )
    if (
        "stream has ended unexpectedly" in lowered
        or "eof marker not found" in lowered
        or "broken xref" in lowered
        or "malformed" in lowered
        or "trailer" in lowered
        or "unexpectedly" in lowered
    ):
        return LegacyPdfExtractError(
            error_type="pdf_corrupted_or_malformed",
            error_stage="extract_text_failed",
            suggestion="该 PDF 更像是文件损坏、下载不完整或结构异常。",
            fallback_plan="建议先重新下载/重新上传；如仍失败，可尝试备用提取器做人工补救。",
        )
    return LegacyPdfExtractError(
        error_type="pdf_extract_exception",
        error_stage="extract_text_failed",
        suggestion="PDF 提取阶段发生异常，请优先检查文件本身是否完整、可打开。",
        fallback_plan="建议先重新上传 PDF；如仍失败，再尝试备用提取器。",
    )


def extract_pdf_text_with_legacy_adapter(pdf_path: Path) -> LegacyPdfExtractResult:
    path = Path(pdf_path).expanduser()
    if not path.exists():
        return LegacyPdfExtractResult(
            ok=False,
            error=f"File not found: {path}",
            error_type="pdf_file_missing",
            error_stage="extract_text_failed",
            suggestion="服务器上未找到该 PDF 文件，请确认上传或下载是否成功。",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = PdfReader(str(path))
            pages = [
                LegacyPdfPage(page=index, text=(page.extract_text() or "").strip())
                for index, page in enumerate(reader.pages, start=1)
            ]
    except Exception as exc:
        classified = classify_pdf_extract_error(exc)
        return LegacyPdfExtractResult(
            ok=False,
            error=str(exc),
            error_type=classified.error_type,
            error_stage=classified.error_stage,
            suggestion=classified.suggestion,
        )

    text = "\n".join(page.text for page in pages if page.text).strip()
    if len(text) < MIN_EXTRACTED_TEXT_CHARS:
        return LegacyPdfExtractResult(
            ok=False,
            page_count=len(pages),
            pages=pages,
            error="PDF can be opened but extracted text is nearly empty.",
            error_type="empty_text_pdf",
            error_stage="extract_text_failed",
            suggestion="PDF 可以打开，但提取到的文本几乎为空，可能是特殊编码或扫描版。",
        )

    return LegacyPdfExtractResult(
        ok=True,
        text=text,
        page_count=len(pages),
        pages=pages,
    )

"""PDF text extraction helpers."""

import warnings
from pathlib import Path

from pypdf import PdfReader


class PdfTextExtractionError(RuntimeError):
    pass


def extract_pdf_text(pdf_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = PdfReader(str(pdf_path))
            page_texts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise PdfTextExtractionError(str(exc)) from exc

    extracted_text = "\n".join(text.strip() for text in page_texts if text.strip()).strip()
    if not extracted_text:
        raise PdfTextExtractionError("No extractable text found in PDF.")

    output_path.write_text(extracted_text, encoding="utf-8")
    return output_path

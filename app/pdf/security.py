"""PDF upload validation."""

from pathlib import Path


PDF_MAGIC_BYTES = b"%PDF-"


class PdfValidationError(ValueError):
    pass


def validate_pdf_upload(
    *,
    filename: str,
    content: bytes,
    max_size_bytes: int,
) -> None:
    if not content:
        raise PdfValidationError("Uploaded PDF is empty.")

    if len(content) > max_size_bytes:
        raise PdfValidationError("Uploaded PDF is too large.")

    if Path(filename).suffix.lower() != ".pdf":
        raise PdfValidationError("Only .pdf files are allowed.")

    if not content.startswith(PDF_MAGIC_BYTES):
        raise PdfValidationError("Uploaded file does not have PDF magic bytes.")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import CitingPaper, PdfAsset, Publication
from app.pdf.extract import extract_pdf_text
from app.pdf.security import PdfValidationError, validate_pdf_upload
from app.repositories.pdf_repo import PdfRepository
from app.services.pdf_service import PdfService


def build_minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_id} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


VALID_PDF_BYTES = build_minimal_pdf("Extractable academic impact text")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_citing_paper(db_session):
    publication = Publication(title="Citing paper")
    db_session.add(publication)
    db_session.flush()
    citing_paper = CitingPaper(
        paper_session_id=1,
        publication_id=publication.id,
        analysis_status="discovered",
    )
    db_session.add(citing_paper)
    db_session.commit()
    db_session.refresh(citing_paper)
    return citing_paper


def test_validate_pdf_rejects_empty_file():
    with pytest.raises(PdfValidationError, match="empty"):
        validate_pdf_upload(
            filename="paper.pdf",
            content=b"",
            max_size_bytes=100,
        )


def test_validate_pdf_rejects_non_pdf_extension():
    with pytest.raises(PdfValidationError, match="Only .pdf"):
        validate_pdf_upload(
            filename="paper.txt",
            content=VALID_PDF_BYTES,
            max_size_bytes=1000,
        )


def test_validate_pdf_rejects_non_pdf_magic_bytes():
    with pytest.raises(PdfValidationError, match="magic bytes"):
        validate_pdf_upload(
            filename="paper.pdf",
            content=b"not a pdf",
            max_size_bytes=1000,
        )


def test_validate_pdf_rejects_oversized_file():
    with pytest.raises(PdfValidationError, match="too large"):
        validate_pdf_upload(
            filename="paper.pdf",
            content=VALID_PDF_BYTES,
            max_size_bytes=10,
        )


def test_extract_pdf_text_success(tmp_path):
    pdf_path = tmp_path / "paper.pdf"
    output_path = tmp_path / "paper.txt"
    pdf_path.write_bytes(VALID_PDF_BYTES)

    extracted_path = extract_pdf_text(pdf_path, output_path)

    assert extracted_path == output_path
    assert "Extractable academic impact text" in output_path.read_text(encoding="utf-8")


def test_upload_legal_pdf_creates_asset_and_extracts_text(db_session, tmp_path):
    citing_paper = create_citing_paper(db_session)
    service = PdfService(
        repository=PdfRepository(db_session),
        pdf_asset_dir=tmp_path / "pdf_assets",
        extracted_text_dir=tmp_path / "extracted_text",
        max_upload_bytes=100000,
    )

    asset = service.upload_pdf_for_citing_paper(
        citing_paper_id=citing_paper.id,
        filename="user-file.pdf",
        content=VALID_PDF_BYTES,
        mime_type="application/pdf",
    )

    refreshed_citing_paper = db_session.get(CitingPaper, citing_paper.id)
    assert refreshed_citing_paper.pdf_asset_id == asset.id
    assert asset.original_filename == "user-file.pdf"
    assert asset.storage_path.endswith(".pdf")
    assert "user-file.pdf" not in asset.storage_path
    assert asset.sha256 is not None
    assert asset.extract_status == "succeeded"
    assert asset.extracted_text_path is not None
    assert "Extractable academic impact text" in (
        tmp_path / "extracted_text" / f"{asset.id}.txt"
    ).read_text(encoding="utf-8")


def test_extract_failure_sets_failed_status(db_session, tmp_path):
    citing_paper = create_citing_paper(db_session)
    service = PdfService(
        repository=PdfRepository(db_session),
        pdf_asset_dir=tmp_path / "pdf_assets",
        extracted_text_dir=tmp_path / "extracted_text",
        max_upload_bytes=100000,
    )

    asset = service.upload_pdf_for_citing_paper(
        citing_paper_id=citing_paper.id,
        filename="empty-text.pdf",
        content=b"%PDF-1.4\n%%EOF",
        mime_type="application/pdf",
    )

    saved_asset = db_session.get(PdfAsset, asset.id)
    assert saved_asset.extract_status == "failed"
    assert saved_asset.extracted_text_path is None

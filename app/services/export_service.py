"""Write generated reports to the local export directory."""

from pathlib import Path

from fastapi import Depends

from app.core.config import settings
from app.services.report_service import ReportService, get_report_service


class ExportService:
    def __init__(self, *, report_service: ReportService, export_dir: Path) -> None:
        self.report_service = report_service
        self.export_dir = export_dir

    def write_report_markdown(self, session_id: int) -> Path:
        export_path = self._session_export_dir(session_id) / "report.md"
        export_path.write_text(
            self.report_service.build_report_markdown(session_id),
            encoding="utf-8",
        )
        return export_path

    def write_structured_json(self, session_id: int) -> Path:
        export_path = self._session_export_dir(session_id) / "structured.json"
        export_path.write_text(
            self.report_service.build_structured_json(session_id),
            encoding="utf-8",
        )
        return export_path

    def _session_export_dir(self, session_id: int) -> Path:
        path = self.export_dir / f"paper_session_{session_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path


def get_export_service(
    report_service: ReportService = Depends(get_report_service),
) -> ExportService:
    return ExportService(
        report_service=report_service,
        export_dir=Path(settings.export_dir),
    )

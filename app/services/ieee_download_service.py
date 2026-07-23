"""Adapter for the user-managed IEEE Playwright downloader CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Optional


_OUTPUT_PATTERNS = (
    re.compile(r"\[成功\]\s+(.+?\.pdf)\s*$"),
    re.compile(r"\[跳过\]\s+已存在：\s*(.+?\.pdf)\s*$"),
)
_LOGIN_MARKERS = (
    "[需要登录]",
    "institutional sign in",
    "机构登录仍未生效",
    "当前 ieee 机构会话已经失效",
    "返回内容不是 pdf",
)


@dataclass(frozen=True)
class IeeeDownloadResult:
    status: str
    output: str
    pdf_path: Optional[Path] = None
    reason: str = ""


class IeeeDownloaderConfigurationError(RuntimeError):
    pass


class IeeeBrowserDownloader:
    """Runs the supplied ``ieee-download`` tool without invoking a shell."""

    def __init__(
        self,
        *,
        command: str,
        work_dir: str = "",
        download_dir: str = "",
        timeout_seconds: int = 900,
    ) -> None:
        self.command = command.strip()
        self.work_dir = Path(work_dir).expanduser().resolve() if work_dir else None
        self.download_dir = (
            Path(download_dir).expanduser().resolve() if download_dir else None
        )
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        if not self.command:
            return False
        executable = shlex.split(self.command)[0]
        return Path(executable).expanduser().is_file() or shutil.which(executable) is not None

    def download(self, query: str) -> IeeeDownloadResult:
        if not self.configured:
            raise IeeeDownloaderConfigurationError(
                "IEEE downloader is not configured or executable"
            )
        query = " ".join(query.split())
        if not query or len(query) > 1000:
            raise ValueError("IEEE download query is invalid")

        command = [*shlex.split(self.command), "-y", query]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.work_dir) if self.work_dir else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = _safe_output(exc.stdout)
            return IeeeDownloadResult("failed", output, reason="download_timeout")

        output = _safe_output(completed.stdout)
        if any(marker.casefold() in output.casefold() for marker in _LOGIN_MARKERS):
            return IeeeDownloadResult("requires_login", output, reason="ieee_session_required")

        pdf_path = self._pdf_path_from_output(output)
        if completed.returncode != 0 or pdf_path is None:
            return IeeeDownloadResult("failed", output, reason="download_failed")
        file_status = self._pdf_file_status(pdf_path)
        if file_status == "login_page":
            return IeeeDownloadResult(
                "requires_login", output, reason="ieee_session_required"
            )
        if file_status != "complete_pdf":
            return IeeeDownloadResult("failed", output, reason="invalid_pdf_output")
        return IeeeDownloadResult("downloaded", output, pdf_path=pdf_path)

    def _pdf_path_from_output(self, output: str) -> Optional[Path]:
        allowed_dir = self._allowed_download_dir()
        for line in output.splitlines():
            for pattern in _OUTPUT_PATTERNS:
                match = pattern.search(line.strip())
                if not match:
                    continue
                candidate = Path(match.group(1).strip()).expanduser()
                if not candidate.is_absolute():
                    candidate = ((self.work_dir or Path.cwd()) / candidate).resolve()
                else:
                    candidate = candidate.resolve()
                try:
                    candidate.relative_to(allowed_dir)
                except ValueError:
                    continue
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
        return None

    def _allowed_download_dir(self) -> Path:
        if self.download_dir:
            return self.download_dir
        if self.work_dir:
            return (self.work_dir / "downloads").resolve()
        raise IeeeDownloaderConfigurationError(
            "ACADEMIC_IMPACT_IEEE_DOWNLOADER_DOWNLOAD_DIR is required when no work directory is set"
        )

    @staticmethod
    def _pdf_file_status(path: Path) -> str:
        with path.open("rb") as handle:
            prefix = handle.read(4096)
            if not prefix.startswith(b"%PDF-"):
                lowered = prefix.lower()
                if b"<html" in lowered and (
                    b"sign in" in lowered or b"login" in lowered
                ):
                    return "login_page"
                return "invalid"
            size = path.stat().st_size
            handle.seek(max(0, size - 16384))
            return "complete_pdf" if b"%%EOF" in handle.read() else "invalid"


def _safe_output(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "")[-100_000:]

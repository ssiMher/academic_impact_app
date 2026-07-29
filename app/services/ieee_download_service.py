"""Adapter for the user-managed IEEE Playwright downloader CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Optional

from app.core.config import PROJECT_ROOT
from app.services.ieee_session_service import IeeeProfileLease


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
_CHALLENGE_MARKERS = (
    "max challenge attempts exceeded",
    "captcha",
    "request rejected",
    "http 403",
    "http 429",
    "too many requests",
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
        profile_dir: str = "",
        runtime_dir: str = "",
        timeout_seconds: int = 900,
    ) -> None:
        self.command = command.strip()
        self.work_dir = Path(work_dir).expanduser().resolve() if work_dir else None
        self.download_dir = (
            Path(download_dir).expanduser().resolve() if download_dir else None
        )
        self.profile_dir = (
            Path(profile_dir).expanduser().resolve()
            if profile_dir
            else ((self.work_dir / "ieee_profile").resolve() if self.work_dir else None)
        )
        self.runtime_dir = (
            Path(runtime_dir).expanduser().resolve()
            if runtime_dir
            else (PROJECT_ROOT / "var" / "run" / "ieee")
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
            with IeeeProfileLease(self.profile_dir, self.runtime_dir):
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
        if any(marker in output.casefold() for marker in _CHALLENGE_MARKERS):
            return IeeeDownloadResult(
                "challenge_blocked",
                output,
                reason="ieee_challenge_blocked",
            )
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

    def download_many(
        self,
        requests: list[dict],
        *,
        min_interval_seconds: float = 8.0,
        stop_file: Optional[Path] = None,
    ) -> list[dict]:
        """Run the supplied downloader functions in one persistent context."""
        if not requests:
            return []
        if not self.configured or not self.work_dir:
            raise IeeeDownloaderConfigurationError(
                "IEEE downloader work directory is not configured"
            )
        python = self.work_dir / ".venv" / "bin" / "python"
        tool_module = self.work_dir / "ieee_download.py"
        helper = PROJECT_ROOT / "scripts" / "ieee_browser_session_helper.py"
        if not python.is_file() or not tool_module.is_file() or not helper.is_file():
            raise IeeeDownloaderConfigurationError(
                "IEEE batch helper requires the configured downloader virtual environment"
            )
        input_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix="ieee_batch_",
                dir=str(self.work_dir),
                delete=False,
            ) as handle:
                json.dump(requests, handle, ensure_ascii=False)
                input_path = Path(handle.name)
            with IeeeProfileLease(self.profile_dir, self.runtime_dir):
                completed = subprocess.run(
                    [
                        str(python),
                        str(helper),
                        "batch",
                        "--tool-module",
                        str(tool_module),
                        "--profile-dir",
                        str(self.profile_dir),
                        "--input",
                        str(input_path),
                        "--interval",
                        str(max(min_interval_seconds, 0)),
                        *(
                            ["--stop-file", str(stop_file)]
                            if stop_file is not None
                            else []
                        ),
                    ],
                    cwd=str(self.work_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=max(self.timeout_seconds * len(requests), self.timeout_seconds),
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            return [
                {
                    "queue_item_id": request["queue_item_id"],
                    "status": "failed",
                    "reason": "download_timeout",
                    "output": _safe_output(exc.stdout),
                }
                for request in requests
            ]
        finally:
            if input_path is not None:
                input_path.unlink(missing_ok=True)

        output = _safe_output(completed.stdout)
        results = []
        session_status = ""
        for line in (completed.stdout or "").splitlines():
            if not line.startswith("IEEE_SESSION_JSON:"):
                continue
            try:
                value = json.loads(line.split(":", 1)[1])
            except json.JSONDecodeError:
                continue
            if value.get("event") == "session":
                session_status = str(value.get("status") or "")
            elif value.get("event") == "result":
                value["output"] = output
                results.append(value)
        processed = {int(value["queue_item_id"]) for value in results}
        if session_status != "authenticated":
            status = (
                "challenge_blocked"
                if session_status == "challenge_blocked"
                else (
                    "paused"
                    if session_status == "paused"
                    else "requires_login"
                )
            )
            reason = (
                "ieee_challenge_blocked"
                if status == "challenge_blocked"
                else (
                    "task_paused"
                    if status == "paused"
                    else "ieee_session_required"
                )
            )
            for request in requests:
                if int(request["queue_item_id"]) not in processed:
                    results.append(
                        {
                            "queue_item_id": request["queue_item_id"],
                            "status": status,
                            "reason": reason,
                            "output": output,
                        }
                    )
        return results

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

"""Manage the user-operated IEEE browser profile without handling credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
import errno
from pathlib import Path
import shlex
import signal
import subprocess
import time
from typing import Optional

from app.core.config import PROJECT_ROOT, settings


logger = logging.getLogger(__name__)


SESSION_STATES = {
    "unauthenticated",
    "waiting_for_login",
    "authenticated",
    "session_expired",
    "challenge_blocked",
    "failed",
}
SESSION_VALIDATION_VERSION = 2


@dataclass(frozen=True)
class IeeeSessionStatus:
    status: str
    personal_login: bool = False
    institution_access: bool = False
    institution_name: str = ""
    challenge_detected: bool = False
    profile_exists: bool = False
    profile_locked: bool = False
    login_window_open: bool = False
    message: str = ""
    last_successful_download_at: Optional[str] = None


class IeeeSessionService:
    """Controls the existing downloader's persistent-profile login process."""

    def __init__(
        self,
        *,
        command: Optional[str] = None,
        work_dir: Optional[str] = None,
        profile_dir: Optional[str] = None,
        runtime_dir: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        self.command = (command if command is not None else settings.ieee_downloader_command).strip()
        raw_work_dir = work_dir if work_dir is not None else settings.ieee_downloader_work_dir
        self.work_dir = Path(raw_work_dir).expanduser().resolve() if raw_work_dir else None
        raw_profile = profile_dir if profile_dir is not None else settings.ieee_profile_dir
        self.profile_dir = (
            Path(raw_profile).expanduser().resolve()
            if raw_profile
            else ((self.work_dir / "ieee_profile").resolve() if self.work_dir else None)
        )
        raw_runtime = (
            runtime_dir if runtime_dir is not None else settings.ieee_runtime_dir
        )
        self.runtime_dir = (
            Path(raw_runtime).expanduser().resolve()
            if raw_runtime
            else (PROJECT_ROOT / "var" / "run" / "ieee")
        )
        self.timeout_seconds = timeout_seconds or settings.ieee_downloader_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.command and self.work_dir and self.profile_dir)

    @property
    def state_path(self) -> Path:
        return self.runtime_dir / "state.json"

    @property
    def legacy_state_path(self) -> Optional[Path]:
        return (
            self.work_dir / ".academic_impact_ieee_state.json"
            if self.work_dir
            else None
        )

    @property
    def fifo_path(self) -> Path:
        # Windows-mounted filesystems such as /mnt/c and /mnt/d do not
        # reliably support Unix FIFOs. Keep process-control files on Linux.
        return self.runtime_dir / "login.fifo"

    @property
    def log_path(self) -> Path:
        return self.runtime_dir / "login.log"

    def pause_path(self, task_id: int) -> Path:
        return self.runtime_dir / f"pause_{int(task_id)}"

    @property
    def lock_path(self) -> Path:
        if not self.profile_dir:
            raise RuntimeError("IEEE profile directory is not configured")
        return self.runtime_dir / "profile.lock"

    def status(self, *, probe: bool = False) -> IeeeSessionStatus:
        state = self._read_state()
        pid = int(state.get("login_pid") or 0)
        expected_start_time = str(state.get("login_pid_start_time") or "")
        process_alive = _pid_alive(pid, expected_start_time)
        started_at = float(state.get("login_started_at_epoch") or 0)
        within_startup_grace = (
            process_alive and started_at > 0 and time.time() - started_at < 15
        )
        login_open = process_alive and (
            within_startup_grace or _browser_process_alive(pid)
        )
        status = str(state.get("status") or "unauthenticated")
        validation_version = int(state.get("session_validation_version") or 0)
        if (
            status == "authenticated"
            and validation_version < SESSION_VALIDATION_VERSION
            and not login_open
        ):
            status = "session_expired"
            state = {
                **state,
                "status": status,
                "personal_login": False,
                "institution_access": False,
                "institution_name": "",
                "message": "旧版 IEEE 登录判断已失效，请重新检测登录状态。",
                "updated_at": _utcnow(),
            }
            self._write_state(state)
        if status == "waiting_for_login" and not login_open:
            if process_alive and expected_start_time:
                self._terminate_login_process(pid)
            status = "unauthenticated"
            state = {
                **state,
                "status": status,
                "login_pid": None,
                "login_pid_start_time": None,
                "login_started_at_epoch": None,
                "message": "IEEE 登录窗口已退出，请重新打开后完成登录。",
                "updated_at": _utcnow(),
            }
            self._write_state(state)
            self._release_profile_lock()
            self.fifo_path.unlink(missing_ok=True)
        if probe and not login_open and self.configured:
            probed = self._run_helper("probe")
            if probed:
                self._write_state(
                    {
                        **state,
                        **probed,
                        "login_pid": None,
                        "login_pid_start_time": None,
                        "login_started_at_epoch": None,
                    }
                )
                state = self._read_state()
                status = str(state.get("status") or status)
        return IeeeSessionStatus(
            status=status if status in SESSION_STATES else "failed",
            personal_login=bool(state.get("personal_login")),
            institution_access=bool(state.get("institution_access")),
            institution_name=str(state.get("institution_name") or ""),
            challenge_detected=bool(state.get("challenge_detected")),
            profile_exists=bool(self.profile_dir and self.profile_dir.exists()),
            profile_locked=self._profile_locked(),
            login_window_open=login_open,
            message=str(state.get("message") or ""),
            last_successful_download_at=state.get("last_successful_download_at"),
        )

    def open_login_window(self) -> IeeeSessionStatus:
        if not self.configured:
            raise RuntimeError("IEEE downloader is not configured")
        current = self.status()
        if current.login_window_open:
            return current
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.fifo_path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_profile_lock(os.getpid())
        fifo_handle = None
        log_handle = None
        try:
            if self.fifo_path.exists():
                self.fifo_path.unlink()
            os.mkfifo(self.fifo_path, 0o600)
            # O_RDWR lets the child keep both FIFO ends open. It must remain
            # blocking so the downloader's input() waits instead of raising EOF.
            fifo_handle = os.open(self.fifo_path, os.O_RDWR)
            log_handle = self.log_path.open("ab")
            process = subprocess.Popen(
                [*shlex.split(self.command), "--login"],
                cwd=str(self.work_dir),
                stdin=fifo_handle,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception as exc:
            logger.exception("Unable to start the IEEE login browser")
            self.fifo_path.unlink(missing_ok=True)
            self._release_profile_lock()
            self.record_failure(
                f"IEEE 登录窗口启动失败：{type(exc).__name__}。"
                "请检查下载器配置和服务器图形环境。"
            )
            raise
        finally:
            if fifo_handle is not None:
                os.close(fifo_handle)
            if log_handle is not None:
                log_handle.close()
        self.lock_path.write_text(str(process.pid), encoding="ascii")
        self._write_state(
            {
                "status": "waiting_for_login",
                "login_pid": process.pid,
                "login_pid_start_time": _process_start_time(process.pid),
                "login_started_at_epoch": time.time(),
                "message": "请在专用 IEEE 浏览器中完成个人或机构登录，然后检测登录状态。",
                "challenge_detected": False,
                "updated_at": _utcnow(),
            }
        )
        return self.status()

    def check_login_status(self) -> IeeeSessionStatus:
        state = self._read_state()
        pid = int(state.get("login_pid") or 0)
        expected_start_time = str(state.get("login_pid_start_time") or "")
        if _pid_alive(pid, expected_start_time):
            if not self._finish_login_process(pid, expected_start_time):
                # A live/reused PID with no FIFO reader must never block the
                # request. Only terminate a process whose start time matches.
                if expected_start_time and _pid_alive(pid, expected_start_time):
                    self._terminate_login_process(pid)
        self._release_profile_lock()
        self.fifo_path.unlink(missing_ok=True)
        probed = self._run_helper("probe")
        if probed:
            self._write_state(
                {
                    **state,
                    **probed,
                    "login_pid": None,
                    "login_pid_start_time": None,
                    "login_started_at_epoch": None,
                    "updated_at": _utcnow(),
                }
            )
        return self.status()

    def reset(self) -> IeeeSessionStatus:
        self.close_login_window()
        self._write_state(
            {
                "status": "unauthenticated",
                "login_pid": None,
                "login_pid_start_time": None,
                "login_started_at_epoch": None,
                "message": "IEEE 会话状态已重置；持久 profile 未删除。",
                "challenge_detected": False,
                "updated_at": _utcnow(),
            }
        )
        return self.status()

    def close_login_window(self) -> IeeeSessionStatus:
        state = self._read_state()
        pid = int(state.get("login_pid") or 0)
        expected_start_time = str(state.get("login_pid_start_time") or "")
        if _pid_alive(pid, expected_start_time):
            self._terminate_login_process(pid)
            deadline = time.monotonic() + 5
            while (
                _pid_alive(pid, expected_start_time)
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if _pid_alive(pid, expected_start_time):
                return self.status()
        self._release_profile_lock()
        self.fifo_path.unlink(missing_ok=True)
        self._write_state(
            {
                **state,
                "login_pid": None,
                "login_pid_start_time": None,
                "login_started_at_epoch": None,
                "updated_at": _utcnow(),
            }
        )
        return self.status()

    def record_failure(self, message: str) -> IeeeSessionStatus:
        state = self._read_state()
        self._write_state(
            {
                **state,
                "status": "failed",
                "login_pid": None,
                "login_pid_start_time": None,
                "login_started_at_epoch": None,
                "message": message[:500],
                "updated_at": _utcnow(),
            }
        )
        return self.status()

    def record_challenge(self, message: str) -> None:
        state = self._read_state()
        self._write_state(
            {
                **state,
                "status": "challenge_blocked",
                "challenge_detected": True,
                "message": message[:500],
                "updated_at": _utcnow(),
            }
        )

    def record_download_success(self) -> None:
        state = self._read_state()
        self._write_state(
            {
                **state,
                "status": "authenticated",
                "session_validation_version": SESSION_VALIDATION_VERSION,
                "last_successful_download_at": _utcnow(),
                "message": "最近一次 IEEE PDF 下载成功。",
                "updated_at": _utcnow(),
            }
        )

    def request_pause(self, task_id: int) -> None:
        if not self.work_dir:
            return
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.pause_path(task_id).touch(mode=0o600, exist_ok=True)

    def clear_pause_request(self, task_id: int) -> None:
        if self.work_dir:
            self.pause_path(task_id).unlink(missing_ok=True)

    def _finish_login_process(
        self,
        pid: int,
        expected_start_time: str = "",
    ) -> bool:
        descriptor = None
        try:
            descriptor = os.open(
                self.fifo_path,
                os.O_WRONLY | os.O_NONBLOCK,
            )
            os.write(descriptor, b"\n")
        except OSError as exc:
            if exc.errno not in {errno.ENXIO, errno.ENOENT, errno.EPIPE}:
                logger.warning("Unable to signal IEEE login process", exc_info=True)
            return False
        finally:
            if descriptor is not None:
                os.close(descriptor)
        deadline = time.monotonic() + 15
        while (
            _pid_alive(pid, expected_start_time)
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        return not _pid_alive(pid, expected_start_time)

    @staticmethod
    def _terminate_login_process(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def _run_helper(self, mode: str) -> dict:
        python = self._helper_python()
        tool_module = self.work_dir / "ieee_download.py"
        helper = PROJECT_ROOT / "scripts" / "ieee_browser_session_helper.py"
        if not python.is_file() or not tool_module.is_file() or not helper.is_file():
            return {
                "status": "unauthenticated",
                "message": "无法运行 IEEE 会话检测；请检查下载器虚拟环境和工具目录。",
            }
        try:
            with IeeeProfileLease(self.profile_dir, self.runtime_dir):
                completed = subprocess.run(
                    [
                        str(python),
                        str(helper),
                        mode,
                        "--tool-module",
                        str(tool_module),
                        "--profile-dir",
                        str(self.profile_dir),
                    ],
                    cwd=str(self.work_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=min(self.timeout_seconds, 180),
                    check=False,
                )
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            return {
                "status": "failed",
                "message": f"IEEE 会话检测失败：{type(exc).__name__}",
            }
        for line in reversed((completed.stdout or "").splitlines()):
            if line.startswith("IEEE_SESSION_JSON:"):
                try:
                    value = json.loads(line.split(":", 1)[1])
                except json.JSONDecodeError:
                    break
                if isinstance(value, dict):
                    return value
        return {
            "status": "failed",
            "message": "IEEE 会话检测失败。",
        }

    def _helper_python(self) -> Path:
        return self.work_dir / ".venv" / "bin" / "python"

    def _read_state(self) -> dict:
        if not self.configured:
            return {}
        path = self.state_path
        if not path.is_file() and self.legacy_state_path is not None:
            path = self.legacy_state_path
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write_state(self, value: dict) -> None:
        if not self.configured:
            return
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.state_path)

    def _profile_locked(self) -> bool:
        if not self.profile_dir or not self.lock_path.is_file():
            return False
        try:
            pid = int(self.lock_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return True
        if _pid_alive(pid):
            return True
        self._release_profile_lock()
        return False

    def _acquire_profile_lock(self, owner_pid: int) -> None:
        if self._profile_locked():
            raise RuntimeError("IEEE persistent profile is already in use")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(descriptor, str(owner_pid).encode("ascii"))
        finally:
            os.close(descriptor)

    def _release_profile_lock(self) -> None:
        if not self.profile_dir or not self.lock_path.exists():
            return
        try:
            self.lock_path.unlink()
        except OSError:
            logger.warning("Unable to remove stale IEEE profile lock", exc_info=True)


class IeeeProfileLease:
    """Process-scoped lock preventing concurrent Chromium profile use."""

    def __init__(
        self,
        profile_dir: Optional[Path],
        runtime_dir: Optional[Path] = None,
    ) -> None:
        self.profile_dir = profile_dir
        self.lock_path = (
            (runtime_dir or (PROJECT_ROOT / "var" / "run" / "ieee"))
            / "profile.lock"
            if profile_dir
            else None
        )

    def __enter__(self):
        if self.lock_path is None:
            raise RuntimeError("IEEE profile directory is not configured")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                owner = int(self.lock_path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                owner = -1
            if owner < 0 or _pid_alive(owner):
                raise RuntimeError("IEEE persistent profile is already in use")
            self.lock_path.unlink(missing_ok=True)
        descriptor = os.open(
            self.lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
        finally:
            os.close(descriptor)
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        if self.lock_path:
            self.lock_path.unlink(missing_ok=True)


def _pid_alive(pid: int, expected_start_time: str = "") -> bool:
    if pid <= 0:
        return False
    process_state, start_time = _read_proc_stat(pid)
    if process_state:
        if process_state == "Z":
            return False
        if expected_start_time and start_time != expected_start_time:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_start_time(pid: int) -> str:
    return _read_proc_stat(pid)[1]


def _browser_process_alive(process_group_id: int) -> bool:
    if process_group_id <= 0:
        return False
    browser_tokens = ("chromium", "chrome", "msedge", "playwright")
    try:
        process_dirs = list(Path("/proc").iterdir())
    except OSError:
        return False
    for proc_dir in process_dirs:
        if not proc_dir.name.isdigit():
            continue
        candidate_pid = int(proc_dir.name)
        if candidate_pid == process_group_id:
            continue
        try:
            if os.getpgid(candidate_pid) != process_group_id:
                continue
            command = (
                (proc_dir / "cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", errors="ignore")
                .casefold()
            )
        except (OSError, ProcessLookupError, PermissionError):
            continue
        if any(token in command for token in browser_tokens):
            return True
    return False


def _read_proc_stat(pid: int) -> tuple[str, str]:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except OSError:
        return "", ""
    # The process name is parenthesized and may itself contain spaces.
    remainder = value.rsplit(")", 1)[-1].strip().split()
    state = remainder[0] if remainder else ""
    start_time = remainder[19] if len(remainder) > 19 else ""
    return state, start_time


def _utcnow() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

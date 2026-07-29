#!/usr/bin/env python3
"""Run the supplied IEEE downloader functions in one persistent context."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
from typing import Optional


CHALLENGE_MARKERS = (
    "max challenge attempts exceeded",
    "captcha",
    "request rejected",
    "access denied",
    "too many requests",
)
LOGIN_MARKERS = (
    "institutional sign in",
    "personal sign in",
    "sign in to access",
    "create account",
)
SESSION_VALIDATION_VERSION = 2


def load_tool(path: Path):
    spec = importlib.util.spec_from_file_location("academic_impact_ieee_tool", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load IEEE downloader module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify_session_text(text: str) -> dict:
    normalized = " ".join((text or "").split())
    lowered = normalized.casefold()
    challenge = any(marker in lowered for marker in CHALLENGE_MARKERS)
    institution_access = "access provided by" in lowered
    # Anonymous IEEE pages contain "My Account" and "Personal Account".
    # Only an explicit logout control is a reliable personal-login signal.
    personal_login = bool(
        re.search(r"\b(?:sign|log)\s*out\b", lowered)
    )
    institution_name = ""
    if institution_access:
        position = lowered.find("access provided by")
        institution_name = normalized[position : position + 180].split("|", 1)[0].strip()
    if challenge:
        status = "challenge_blocked"
        message = "IEEE 页面出现挑战限制，请在专用浏览器中人工处理或稍后重试。"
    elif institution_access or personal_login:
        status = "authenticated"
        message = "IEEE 个人登录或机构访问已生效。"
    else:
        status = "unauthenticated"
        message = "未检测到可靠的 IEEE 个人登录或机构访问标志。"
    return {
        "status": status,
        "personal_login": personal_login,
        "institution_access": institution_access,
        "institution_name": institution_name,
        "challenge_detected": challenge,
        "message": message,
        "session_validation_version": SESSION_VALIDATION_VERSION,
    }


def inspect_page(page) -> dict:
    try:
        page.goto(
            "https://ieeexplore.ieee.org/",
            wait_until="domcontentloaded",
            timeout=120_000,
        )
        page.wait_for_timeout(2500)
        text = page.locator("body").inner_text(timeout=10_000) or ""
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"session probe failed: {type(exc).__name__}",
            "session_validation_version": SESSION_VALIDATION_VERSION,
        }
    return classify_session_text(text)


def emit(value: dict) -> None:
    print("IEEE_SESSION_JSON:" + json.dumps(value, ensure_ascii=False), flush=True)


def run_probe(tool) -> int:
    with tool.sync_playwright() as playwright:
        context = tool.create_context(playwright)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            emit(inspect_page(page))
        finally:
            context.close()
    return 0


def run_batch(
    tool,
    input_path: Path,
    interval: float,
    stop_file: Optional[Path],
) -> int:
    requests = json.loads(input_path.read_text(encoding="utf-8"))
    with tool.sync_playwright() as playwright:
        context = tool.create_context(playwright)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(tool.DEFAULT_TIMEOUT_MS)
            session = inspect_page(page)
            emit({"event": "session", **session})
            if session["status"] != "authenticated":
                return 3
            for offset, request in enumerate(requests):
                if stop_file is not None and stop_file.exists():
                    emit({"event": "session", "status": "paused"})
                    return 5
                query = str(request["query"])
                try:
                    article_number, selected_title = tool.resolve_query(page, query, True)
                    path = tool.download_article(
                        context,
                        page,
                        article_number,
                        selected_title,
                    )
                    emit(
                        {
                            "event": "result",
                            "queue_item_id": request["queue_item_id"],
                            "status": "downloaded",
                            "pdf_path": str(path),
                            "article_number": article_number,
                        }
                    )
                except Exception as exc:
                    page_state = inspect_current_page(page)
                    emit(
                        {
                            "event": "result",
                            "queue_item_id": request["queue_item_id"],
                            "status": page_state,
                            "reason": _safe_reason(exc),
                        }
                    )
                    if page_state in {"requires_login", "challenge_blocked"}:
                        return 4
                if offset + 1 < len(requests):
                    time.sleep(max(interval, 0))
        finally:
            context.close()
    return 0


def inspect_current_page(page) -> str:
    try:
        text = (page.locator("body").inner_text(timeout=5_000) or "").casefold()
    except Exception:
        return "failed"
    if any(marker in text for marker in CHALLENGE_MARKERS):
        return "challenge_blocked"
    if any(marker in text for marker in LOGIN_MARKERS):
        return "requires_login"
    return "failed"


def _safe_reason(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("probe", "batch"))
    parser.add_argument("--tool-module", type=Path, required=True)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--interval", type=float, default=8.0)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    tool = load_tool(args.tool_module.resolve())
    if args.profile_dir is not None:
        tool.PROFILE_DIR = args.profile_dir.expanduser().resolve()
    if args.mode == "probe":
        return run_probe(tool)
    if args.input is None:
        raise ValueError("--input is required for batch mode")
    return run_batch(tool, args.input, args.interval, args.stop_file)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        emit({"status": "failed", "message": _safe_reason(exc)})
        raise SystemExit(1)

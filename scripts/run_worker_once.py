"""Run at most one pending task."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.worker_entrypoint import run_worker_once


if __name__ == "__main__":
    run_worker_once()

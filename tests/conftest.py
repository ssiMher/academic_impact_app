import os
import sys
from pathlib import Path


os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ACADEMIC_IMPACT_DATABASE_URL", "sqlite:///:memory:")
os.environ["ACADEMIC_IMPACT_AUTHOR_PROVIDER"] = "fake"
os.environ["ACADEMIC_IMPACT_CITATION_PROVIDER"] = "fake"
os.environ["ACADEMIC_IMPACT_METADATA_PROVIDER"] = "fake"
os.environ["ACADEMIC_IMPACT_LLM_PROVIDER"] = "fake"
os.environ["ACADEMIC_IMPACT_UNPAYWALL_EMAIL"] = ""

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

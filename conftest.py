import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env before any test module is collected so env vars are visible
# to module-level skip markers (requires_github).
load_dotenv(Path(__file__).parent / ".env")

# iac_eval is not an installed package — it lives inside llm_benchmarking/.
# This must be on sys.path before phase3/__init__.py is imported during collection.
_iac_eval_path = str(Path(__file__).parent / "llm_benchmarking" / "IaC-Evaluation-Pipeline")
if _iac_eval_path not in sys.path:
    sys.path.insert(0, _iac_eval_path)

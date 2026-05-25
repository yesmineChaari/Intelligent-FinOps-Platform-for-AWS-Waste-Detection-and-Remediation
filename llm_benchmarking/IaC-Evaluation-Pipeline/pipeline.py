from pathlib import Path
import runpy
import sys


_IMPLEMENTATION_DIR = (
    Path(__file__).resolve().parents[2]
    / "agent2"
    / "llm_benchmarking"
    / "IaC-Evaluation-Pipeline"
)

if __name__ == "__main__":
    sys.path.insert(0, str(_IMPLEMENTATION_DIR))
    runpy.run_path(str(_IMPLEMENTATION_DIR / "pipeline.py"), run_name="__main__")

from pathlib import Path as _Path
import runpy as _runpy


_IMPLEMENTATION = (
    _Path(__file__).resolve().parents[3]
    / "agent2"
    / "llm_benchmarking"
    / "IaC-Evaluation-Pipeline"
    / "prompts"
    / "prompt_builder.py"
)
_namespace = _runpy.run_path(str(_IMPLEMENTATION))
globals().update({name: value for name, value in _namespace.items() if not name.startswith("__")})

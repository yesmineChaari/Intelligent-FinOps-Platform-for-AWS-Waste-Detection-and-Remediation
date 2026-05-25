import sys as _sys

from agent2.phase3 import llm_phase3 as _implementation

_sys.modules[__name__] = _implementation

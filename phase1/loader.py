import sys as _sys

from agent1.phase1 import loader as _implementation

_sys.modules[__name__] = _implementation

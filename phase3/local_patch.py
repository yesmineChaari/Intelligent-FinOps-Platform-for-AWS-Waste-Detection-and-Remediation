import sys as _sys

from agent2.phase3 import local_patch as _implementation

_sys.modules[__name__] = _implementation

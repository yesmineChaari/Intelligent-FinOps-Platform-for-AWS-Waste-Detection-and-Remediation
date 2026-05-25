import sys as _sys

from agent2.phase3 import patch_schema as _implementation

_sys.modules[__name__] = _implementation

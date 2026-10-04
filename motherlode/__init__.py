"""Motherlode: a verifying decompiler for The Sims 4's Python 3.7 bytecode."""

import sys

__version__ = "0.1.0"

if sys.version_info[:2] != (3, 7):
    raise ImportError("Motherlode must run on Python 3.7, the same version The Sims 4 uses (found %d.%d)" % sys.version_info[:2])

from .api import Result, decompile_code, decompile_pyc, decompile_pyc_bytes

__all__ = ["Result", "decompile_code", "decompile_pyc", "decompile_pyc_bytes", "__version__"]

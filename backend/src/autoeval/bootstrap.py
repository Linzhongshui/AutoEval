"""Compatibility entry point: implementation moved to autoeval.infrastructure.bootstrap."""

import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("autoeval.infrastructure.bootstrap", run_name="__main__", alter_sys=True)
else:
    from importlib import import_module

    sys.modules[__name__] = import_module("autoeval.infrastructure.bootstrap")

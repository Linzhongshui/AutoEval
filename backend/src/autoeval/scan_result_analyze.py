"""Compatibility entry point: implementation moved to autoeval.analysis.scan_result_analyze."""

import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("autoeval.analysis.scan_result_analyze", run_name="__main__", alter_sys=True)
else:
    from importlib import import_module

    sys.modules[__name__] = import_module("autoeval.analysis.scan_result_analyze")

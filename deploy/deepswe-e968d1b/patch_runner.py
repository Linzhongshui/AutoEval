"""Patch only the exception logger in the inline Harbor runner; also usable on a staged tool root."""

import ast
import sys
from pathlib import Path


def patch(path):
    source = path.read_text(encoding="utf-8")
    runner = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "HarborRunner")
    inline = next(n for n in runner.body if isinstance(n, ast.FunctionDef) and n.name == "_launch_inline")
    calls = [n for h in ast.walk(inline) if isinstance(h, ast.ExceptHandler)
             for n in h.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and ast.unparse(n.value.func) in ("self.logger.exception", "self.logger.error")]
    if len(calls) != 1:
        raise ValueError("Unknown HarborRunner layout")
    call = calls[0]
    lines = source.splitlines(keepends=True)
    lines[call.lineno-1:call.end_lineno] = [
        " " * call.col_offset + "self.logger.error(RUNNER_CODES.TASK_FAILED, "
        + """f"Harbor agent task '{task_name}' failed in-process", exc_info=True)\n"""
    ]
    updated = "".join(lines)
    compile(updated, str(path), "exec")
    if source != updated:
        path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    patch(Path(sys.argv[1]))

"""Architecture boundary checks: a route handler must never call another
router module's handler directly; shared logic belongs in service modules.

Only ``from autoeval.X import name`` forms are inspected (the codebase style);
importing schemas, ORM classes or constants from sibling modules stays legal.
"""

import ast
from pathlib import Path

from autoeval.api import create_app


def _router_endpoints() -> dict[str, set[str]]:
    endpoints: dict[str, set[str]] = {}
    for route in create_app().routes:
        # Recent FastAPI wraps included routers lazily; unwrap to the APIRouter.
        inner = getattr(route, "original_router", None) or route
        for sub in getattr(inner, "routes", []):
            endpoint = getattr(sub, "endpoint", None)
            if endpoint is None:
                continue
            module = endpoint.__module__
            if module.startswith("autoeval.") and module != "autoeval.api":
                endpoints.setdefault(module, set()).add(endpoint.__name__)
    return endpoints


def test_routes_do_not_import_sibling_route_handlers():
    endpoints = _router_endpoints()
    assert endpoints, "expected registered routers from create_app()"
    src_root = Path(__file__).resolve().parents[1] / "src" / "autoeval"
    violations: list[str] = []
    for module_name in endpoints:
        file = src_root.joinpath(*module_name.split(".")[1:]).with_suffix(".py")
        if not file.exists():
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module and node.level == 0):
                continue
            target = node.module
            if target == module_name or target not in endpoints:
                continue
            for alias in node.names:
                if alias.name in endpoints[target]:
                    violations.append(
                        f"{module_name} imports route handler "
                        f"{target}.{alias.name}; move the shared logic into a service"
                    )
    assert not violations, "\n".join(violations)

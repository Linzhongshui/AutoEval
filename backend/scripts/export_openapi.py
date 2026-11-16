"""Export the FastAPI OpenAPI contract for frontend type generation.

Run from backend/: uv run python scripts/export_openapi.py
Writes backend/openapi.json without connecting to the database; the app
factory only touches external dependencies inside its lifespan handler.
"""

import json
from pathlib import Path

from autoeval.api import create_app


def main() -> None:
    app = create_app()
    schema = app.openapi()
    target = Path(__file__).resolve().parent.parent / "openapi.json"
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"OpenAPI contract exported to {target}")


if __name__ == "__main__":
    main()

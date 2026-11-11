# Repository Guidelines

## Project Structure & Module Organization

- `frontend/src/app/` contains React screens; `frontend/src/components/` holds reusable UI and `frontend/src/services/` API clients. Static assets live in `frontend/public/`.
- `backend/src/autoeval/` contains FastAPI endpoints, domain models, Temporal workflows, workers, and resource/tool adapters. Tests live in `backend/tests/`; Alembic migrations in `backend/migrations/`; approved tool manifests in `backend/tool-locks/`.
- `deploy/` contains Compose definitions and the SSH simulator. `docs/` contains development plans, validation records, and recovery instructions.

## Build, Test, and Development Commands

Run frontend commands from `frontend/`:

```sh
npm ci                 # Install locked dependencies
npm run dev            # Start Vite; proxy API requests to port 8000
npm run typecheck      # Check TypeScript
npm run build          # Type-check and build production assets
```

Run backend commands from `backend/` so local configuration resolves correctly:

```sh
uv sync --frozen --python 3.12
uv run uvicorn autoeval.api:app --host 127.0.0.1 --port 8000
uv run alembic upgrade head
uv run ruff check .
uv run pytest -q
```

API startup alone does not execute tasks. Run the dispatcher, required worker roles, and reconciler as described in `README.md`. Follow `docs/development-recovery.md` for persistent storage setup.

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python functions/modules. Ruff targets Python 3.12 with a 100-character line limit; format only touched files with `uv run ruff format <paths>`. Use two-space indentation, PascalCase React components, and camelCase TypeScript variables. Follow nearby code and retain the existing component library.

## Testing Guidelines

Use pytest, pytest-asyncio, and Playwright; name Python tests `test_*.py`. Add meaningful regression tests for changed behavior. Integration suites require explicit flags such as `AE_INFRA_TEST`, `AE_SSH_SIM_TEST`, and `AE_BROWSER_URL`; document prerequisites and skipped tests. No numeric coverage threshold is configured. Mocked model responses must remain distinguishable from real results and must never trigger paid generation unintentionally.

## Commit & Pull Request Guidelines

Follow existing messages: `feat(frontend): ...` or `fix(m8): ...`. Keep commits cohesive. PRs should describe the problem, resulting behavior, validation commands/results, and remaining limitations; link relevant issues or design documents and include screenshots for visible UI changes. Report environment failures separately from code failures.

## Security & Architecture Boundaries

Keep single-team, single-workspace semantics; do not introduce tenancy implicitly. Never commit credentials, `.env`, protected backups, or generated sharing bundles. Freeze execution inputs and tool identities; preserve failed attempts and historical snapshots. Never fabricate missing evidence, silently reissue uncertain model requests, or treat exploratory scores as Release approval.

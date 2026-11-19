#!/bin/sh
set -eu

# The pinned cli module does not call main() when executed with python -m.
exec /opt/venvs/harbor/bin/python -c 'from autoeval_adaptor.cli import main; raise SystemExit(main())' "$@"

#!/bin/sh
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tmp"
exec "$PWD/../../safelabs-eval/.venv/bin/python" -m pytest -p no:cacheprovider --basetemp="$PWD/tmp/pytest" -q tests "$@"

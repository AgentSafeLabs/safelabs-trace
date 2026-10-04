#!/bin/sh
# Offline tests. Run from this folder. Temp files go to tmp/ (TMPDIR and --basetemp).
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tmp" PYTHONPATH="$PWD:$PWD/../../safelabs-trace/src:$PWD/../../safelabs-eval"
exec "$PWD/../../safelabs-eval/.venv/bin/python" -m pytest -p no:cacheprovider --basetemp="$PWD/tmp/pytest" -q tests "$@"

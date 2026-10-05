#!/bin/sh
# Offline tests. Run from this folder. Temp files go outside the repo (the trace writer refuses capture dirs inside a git tree).
cd "$(dirname "$0")" || exit 1
T="${SAFELABS_TEST_TMP:-/tmp/safelabs-trace-tests}"
mkdir -p "$T" || exit 1
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$T" PYTHONPATH="$PWD:$PWD/../../safelabs-trace/src:$PWD/../../safelabs-eval"
exec "$PWD/../../safelabs-eval/.venv/bin/python" -m pytest -p no:cacheprovider --basetemp="$T/pytest" -q tests "$@"

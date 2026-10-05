#!/bin/sh
# Offline tests. Run from this folder. Temp files go outside the repo (the trace writer refuses capture dirs inside a git tree).
# ROOT is the folder that holds safelabs-trace/ and safelabs-eval/ (found automatically; override with SAFELABS_ROOT).
cd "$(dirname "$0")" || exit 1
if [ -n "$SAFELABS_ROOT" ]; then ROOT="$SAFELABS_ROOT"
elif [ -d ../../safelabs-trace/src ]; then ROOT="$(cd ../.. && pwd)"
else ROOT="$(cd ../../.. && pwd)"; fi
T="${SAFELABS_TEST_TMP:-/tmp/safelabs-trace-tests}"
mkdir -p "$T" || exit 1
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$T" PYTHONPATH="$PWD:$ROOT/safelabs-trace/src:$ROOT/safelabs-eval"
exec "$ROOT/safelabs-eval/.venv/bin/python" -m pytest -p no:cacheprovider --basetemp="$T/pytest" -q tests "$@"

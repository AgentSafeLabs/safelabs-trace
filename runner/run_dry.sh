#!/bin/sh
# Offline dry run: 5 items x 3 frameworks x 3 models with fake models; then a --rerun-missing pass; then a manifest check.
# Usage: sh run_dry.sh [OUT_DIR]   (default /tmp/safelabs-trace-tests/dryrun_out; a folder that already has rows is refused, so give a new name for another run).
# Run from this folder. Temp files and the default output go outside the repo (the trace writer refuses capture dirs inside a git tree), the same way run_tests.sh does.
# ROOT is the folder that holds safelabs-trace/ and safelabs-eval/ (found automatically; override with SAFELABS_ROOT).
cd "$(dirname "$0")" || exit 1
if [ -n "$SAFELABS_ROOT" ]; then ROOT="$SAFELABS_ROOT"
elif [ -d ../../safelabs-trace/src ]; then ROOT="$(cd ../.. && pwd)"
else ROOT="$(cd ../../.. && pwd)"; fi
T="${SAFELABS_TEST_TMP:-/tmp/safelabs-trace-tests}"
mkdir -p "$T" || exit 1
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$T" PYTHONPATH="$PWD:$ROOT/safelabs-trace/src:$ROOT/safelabs-eval"
OUT="${1:-$T/dryrun_out}"
PY="$ROOT/safelabs-eval/.venv/bin/python"
"$PY" -m trace_runner --config configs/dryrun.yaml --dry-run --out "$OUT" &&
"$PY" -m trace_runner --config configs/dryrun.yaml --dry-run --out "$OUT" --rerun-missing &&
"$PY" -m trace_runner --config configs/dryrun.yaml --dry-run --out "$OUT" --verify

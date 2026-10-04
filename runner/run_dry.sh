#!/bin/sh
# Offline dry run: 5 items x 3 frameworks x 3 models with fake models; then a --rerun-missing pass; then a manifest check.
# Usage: sh run_dry.sh [OUT_DIR]   (default dryrun_out; a folder that already has rows is refused, so give a new name for another run).
# Run from this folder. Writes only into the output folder (and tmp/).
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tmp" PYTHONPATH="$PWD:$PWD/../../safelabs-trace/src:$PWD/../../safelabs-eval"
OUT="${1:-dryrun_out}"
PY="$PWD/../../safelabs-eval/.venv/bin/python"
"$PY" -m trace_runner --config configs/dryrun.yaml --dry-run --out "$OUT" &&
"$PY" -m trace_runner --config configs/dryrun.yaml --dry-run --out "$OUT" --rerun-missing &&
"$PY" -m trace_runner --config configs/dryrun.yaml --dry-run --out "$OUT" --verify

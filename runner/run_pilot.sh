#!/bin/sh
# REAL run, started by hand by the person who pays for it. It calls real models and spends money (up to the cap in the config).
# Usage (from this folder, in a shell where you have already loaded your keys yourself; this script never reads a .env file and never prints a key):
#   sh run_pilot.sh configs/pilot.yaml ../../runs/pilot        # the pilot
#   sh run_pilot.sh configs/smoke.yaml ../../runs/smoke2       # a smoke run into a NEW folder (a folder that already has rows is refused)
# Steps: check the four environment variables are non-empty (names only are ever printed) -> --estimate -> wait for Enter -> --confirm-real -> --verify -> print the summary.
# ROOT is the folder that holds safelabs-trace/ and safelabs-eval/ (found automatically; override with SAFELABS_ROOT).
cd "$(dirname "$0")" || exit 1
CONFIG="$1"; OUT="$2"
if [ -z "$CONFIG" ] || [ -z "$OUT" ]; then echo "usage: sh run_pilot.sh CONFIG OUT   (for example: sh run_pilot.sh configs/pilot.yaml ../../runs/pilot)" >&2; exit 2; fi
[ -f "$CONFIG" ] || { echo "refusing: config $CONFIG not found" >&2; exit 2; }
MISSING=""
[ -n "${ANTHROPIC_API_KEY:-}" ]   || MISSING="$MISSING ANTHROPIC_API_KEY"
[ -n "${OPENAI_API_KEY:-}" ]      || MISSING="$MISSING OPENAI_API_KEY"
[ -n "${GEMINI_API_KEY:-}" ]      || MISSING="$MISSING GEMINI_API_KEY"
[ -n "${SAFELABS_TRACE_SALT:-}" ] || MISSING="$MISSING SAFELABS_TRACE_SALT"
if [ -n "$MISSING" ]; then echo "refusing: these environment variables are empty or not set (names only):$MISSING" >&2; exit 2; fi
# no span content, no trace export
export ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false
for V in $(env | awk -F= '/^OTEL_EXPORTER_OTLP_[A-Za-z0-9_]*=/ {print $1}'); do unset "$V"; done
if [ -n "$SAFELABS_ROOT" ]; then ROOT="$SAFELABS_ROOT"
elif [ -d ../../safelabs-trace/src ]; then ROOT="$(cd ../.. && pwd)"
else ROOT="$(cd ../../.. && pwd)"; fi
T="${SAFELABS_TEST_TMP:-/tmp/safelabs-trace-tests}"
mkdir -p "$T" || exit 1
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$T" PYTHONPATH="$PWD:$ROOT/safelabs-trace/src:$ROOT/safelabs-eval"
PY="$ROOT/safelabs-eval/.venv/bin/python"
echo "== 1. estimate (calls nothing) =="
"$PY" -m trace_runner --config "$CONFIG" --estimate || exit 1
echo
echo "This will call real models and spend money. Output folder: $OUT"
printf "Press Enter to start the real run, or Ctrl-C to stop: "
read _ANSWER
echo "== 2. real run =="
"$PY" -m trace_runner --config "$CONFIG" --confirm-real --out "$OUT" || exit 1
echo "== 3. verify =="
"$PY" -m trace_runner --config "$CONFIG" --out "$OUT" --verify || exit 1
echo "== 4. divergence summary =="
cat "$OUT/divergence_summary.md"

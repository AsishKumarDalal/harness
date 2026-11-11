#!/bin/bash
# Run the live (Tier B) suites one after another.
#
# They must NOT overlap: there is ONE model server behind the tunnel, and
# two concurrent benchmark runs would measure each other's latency.
set -u
cd "$(dirname "$0")/.."
mkdir -p benchmark/logs

run () {
  name="$1"; shift
  echo "=== $name started $(date +%H:%M:%S) ==="
  .venv/bin/python -u "benchmark/$name.py" "$@" > "benchmark/logs/$name.log" 2>&1
  echo "=== $name finished $(date +%H:%M:%S) rc=$? ==="
}

run bench_model
run bench_parallel
run bench_agent --repeat "${AGENT_REPEAT:-2}"

echo "ALL LIVE SUITES DONE $(date +%H:%M:%S)"

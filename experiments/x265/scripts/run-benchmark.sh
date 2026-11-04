#!/usr/bin/env bash
# Invoke from the macOS host; requires the prepared running container.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
container="${X265_CONTAINER:-diploma-syntacore-smoke}"
config="${2:-$root/configs/benchmark.json}"
run_id="${1:-comparison-$(date -u +%Y%m%dT%H%M%SZ)}"
[[ "$run_id" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid run identifier' >&2; exit 1; }
local_out="$root/results/$run_id"
remote_out="/opt/diploma/x265-$run_id"
[[ ! -e "$local_out" ]] || { echo "Already exists: $local_out" >&2; exit 1; }
mkdir "$local_out"
docker cp "$root/scripts/benchmark.py" "$container:/opt/diploma/x265-benchmark.py"
docker cp "$config" "$container:/opt/diploma/x265-benchmark.json"
docker cp "$root/inputs/foreman_qcif.y4m" "$container:/opt/diploma/foreman_qcif.y4m"
docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' > "$local_out/host-docker-load.txt"
ps -axo pid,pcpu,comm > "$local_out/host-processes.txt"
status=0
docker exec "$container" python3 /opt/diploma/x265-benchmark.py \
  --config /opt/diploma/x265-benchmark.json --output "$remote_out" || status=$?
# Preserve partial runs and error logs as well as successful results.
docker cp "$container:$remote_out/." "$local_out/"
exit "$status"

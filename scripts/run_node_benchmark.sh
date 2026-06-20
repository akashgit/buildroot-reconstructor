#!/usr/bin/env bash
# Run a list of packages sequentially on this node.
# Usage: run_node_benchmark.sh <node_number> <packages_file>
# Each line in packages_file is a Maven coordinate (groupId:artifactId:version)

set -euo pipefail

NODE="$1"
PACKAGES_FILE="$2"
HOST="ai-innovation-h100-${NODE}-preserve"
OUTPUT_DIR="results/v3-benchmark"
MAX_ITER=15
LOGDIR="results"

cd ~/buildroot-reconstructor

mkdir -p "$OUTPUT_DIR" "$LOGDIR"

echo "=== Node $NODE benchmark started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "Host: $HOST"
echo "Packages:"
cat "$PACKAGES_FILE"
echo "---"

TOTAL=$(grep -c '^[^#]' "$PACKAGES_FILE" || echo 0)
DONE=0
FAILED=0

while IFS= read -r pkg; do
    # Skip comments and blanks
    [[ "$pkg" =~ ^#.*$ || -z "$pkg" ]] && continue

    DONE=$((DONE + 1))
    SAFE_NAME=$(echo "$pkg" | tr ':' '_' | tr '.' '_')
    LOGFILE="$LOGDIR/v3-${SAFE_NAME}.log"

    echo ""
    echo "[$DONE/$TOTAL] Starting: $pkg at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if .venv/bin/python -m buildroot agent "$pkg" \
        --output "$OUTPUT_DIR/" \
        --max-iterations "$MAX_ITER" \
        --host "$HOST" \
        -v < /dev/null > "$LOGFILE" 2>&1; then
        echo "[$DONE/$TOTAL] DONE: $pkg (success)"
    else
        echo "[$DONE/$TOTAL] DONE: $pkg (exit code $?)"
        FAILED=$((FAILED + 1))
    fi
done < "$PACKAGES_FILE"

echo ""
echo "=== Node $NODE benchmark completed at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "Total: $TOTAL | Succeeded: $((TOTAL - FAILED)) | Failed: $FAILED"

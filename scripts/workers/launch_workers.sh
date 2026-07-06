#!/usr/bin/env bash
# Launch parallel worker tmux sessions for the batch build pipeline.
# Automatically resumes from previous runs by excluding already-processed GAVs.
#
# Configuration: set DATABASE_URL, NUM_WORKERS in .env (see .env.example).
# Requires: project .venv with buildroot installed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
BUILDROOT="${PROJECT_DIR}/.venv/bin/buildroot"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "ERROR: .venv not found at ${PROJECT_DIR}/.venv" >&2
    echo "Run: uv venv && uv pip install -e ." >&2
    exit 1
fi

# Load .env
ENV_FILE="${PROJECT_DIR}/.env"
[ -f "${ENV_FILE}" ] && set -a && source "${ENV_FILE}" && set +a

NUM_WORKERS="${NUM_WORKERS:-30}"

echo "=== Splitting GAVs across ${NUM_WORKERS} workers (excluding already-processed) ==="
${VENV_PYTHON} "${SCRIPT_DIR}/split_gavs.py"

echo ""
echo "=== Clearing old progress/log files for fresh monitor counts ==="
for d in "${PROJECT_DIR}"/logs/worker-*; do
    [ -d "$d" ] && rm -rf "$d"
done
echo "  Old logs cleared"

echo ""
echo "=== Pre-warming podman base images ==="
${VENV_PYTHON} -c "
from buildroot.utils.podman_isolation import save_base_images
save_base_images()
print('Prewarm tarball ready')
"
echo "=== Pre-warm complete ==="

echo ""
echo "=== Launching ${NUM_WORKERS} tmux worker sessions ==="

for i in $(seq 0 $((NUM_WORKERS - 1))); do
    session_name="gx-build-reconstructor-worker-${i}"
    gavs_file="${PROJECT_DIR}/gavs/worker-${i}.txt"

    if tmux has-session -t "${session_name}" 2>/dev/null; then
        echo "  worker-${i}: session already exists, skipping"
        continue
    fi

    tmux new-session -d -s "${session_name}" -c "${PROJECT_DIR}" \
        "${SCRIPT_DIR}/run_worker.sh ${i} ${gavs_file}"

    echo "  worker-${i}: launched ($(wc -l < "${gavs_file}" | tr -d ' ') GAVs)"
done

echo ""
echo "=== All workers launched ==="
echo "Monitor with: ${SCRIPT_DIR}/monitor_workers.sh"
echo "Attach to a worker: tmux attach -t gx-build-reconstructor-worker-0"

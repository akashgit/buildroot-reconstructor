#!/usr/bin/env bash
# Worker script: processes assigned GAVs sequentially through the v4 pipeline.
# Usage: run_worker.sh <worker-index> <gavs-file>
#
# Configuration: set DATABASE_URL in .env (see .env.example).
# Requires: project .venv with buildroot installed.
set -euo pipefail

WORKER_ID="$1"
GAVS_FILE="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOG_DIR="${PROJECT_DIR}/logs/worker-${WORKER_ID}"
PROGRESS_FILE="${LOG_DIR}/progress.csv"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
BUILDROOT="${PROJECT_DIR}/.venv/bin/buildroot"

# Load .env
ENV_FILE="${PROJECT_DIR}/.env"
[ -f "${ENV_FILE}" ] && set -a && source "${ENV_FILE}" && set +a

DATABASE_URL="${DATABASE_URL:-postgresql:///postgres}"

mkdir -p "${LOG_DIR}"

if [[ ! -f "${PROGRESS_FILE}" ]]; then
    echo "gav,exit_code,timestamp,elapsed_s" > "${PROGRESS_FILE}"
fi

check_db_exists() {
    local gav="$1"
    local group_id artifact_id version
    IFS=: read -r group_id artifact_id version <<< "${gav}"
    ${VENV_PYTHON} -c "
import sys
try:
    import psycopg2
    conn = psycopg2.connect('${DATABASE_URL}')
    cur = conn.cursor()
    cur.execute('SELECT reward FROM builds WHERE group_id=%s AND artifact_id=%s AND version=%s AND reward >= 0.98', ('${group_id}', '${artifact_id}', '${version}'))
    row = cur.fetchone()
    conn.close()
    sys.exit(0 if row else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

MAX_RETRIES=3

echo "[worker-${WORKER_ID}] Starting at $(date)"
echo "[worker-${WORKER_ID}] GAVs file: ${GAVS_FILE}"
echo "[worker-${WORKER_ID}] Log dir: ${LOG_DIR}"

total=$(wc -l < "${GAVS_FILE}" | tr -d ' ')
count=0

while IFS= read -r gav; do
    [[ -z "${gav}" || "${gav}" == \#* ]] && continue
    count=$((count + 1))

    if check_db_exists "${gav}"; then
        echo "[worker-${WORKER_ID}] [${count}/${total}] SKIP (DB reward>=0.98): ${gav}"
        echo "${gav},0,$(date -Iseconds),0" >> "${PROGRESS_FILE}"
        continue
    fi

    safe_name=$(echo "${gav}" | tr ':.' '_')
    log_file="${LOG_DIR}/${safe_name}.log"

    attempt=0
    while [[ ${attempt} -lt ${MAX_RETRIES} ]]; do
        attempt=$((attempt + 1))
        echo "[worker-${WORKER_ID}] [${count}/${total}] START (attempt ${attempt}/${MAX_RETRIES}): ${gav}"
        start_ts=$(date +%s)

        set +e
        ${BUILDROOT} agent "${gav}" --enable-google-mirror > "${log_file}" 2>&1
        exit_code=$?
        set -e

        elapsed=$(( $(date +%s) - start_ts ))

        if [[ ${exit_code} -eq 0 ]]; then
            echo "${gav},${exit_code},$(date -Iseconds),${elapsed}" >> "${PROGRESS_FILE}"
            echo "[worker-${WORKER_ID}] [${count}/${total}] DONE (exit=0, ${elapsed}s): ${gav}"
            break
        fi

        if [[ ${exit_code} -gt 128 ]]; then
            sig=$((exit_code - 128))
            sig_name=$(kill -l ${sig} 2>/dev/null || echo "SIG${sig}")
            echo "[worker-${WORKER_ID}] [${count}/${total}] KILLED by ${sig_name} (exit=${exit_code}, ${elapsed}s, attempt ${attempt}): ${gav}"
            echo "[worker-${WORKER_ID}]   last 5 lines of log:"
            tail -5 "${log_file}" 2>/dev/null | sed "s/^/[worker-${WORKER_ID}]     /"
        else
            echo "[worker-${WORKER_ID}] [${count}/${total}] FAIL (exit=${exit_code}, ${elapsed}s, attempt ${attempt}): ${gav}"
            echo "[worker-${WORKER_ID}]   last 5 lines of log:"
            tail -5 "${log_file}" 2>/dev/null | sed "s/^/[worker-${WORKER_ID}]     /"
        fi

        if [[ ${attempt} -lt ${MAX_RETRIES} ]]; then
            echo "[worker-${WORKER_ID}]   retrying in 10s..."
            sleep 10
        else
            echo "${gav},${exit_code},$(date -Iseconds),${elapsed}" >> "${PROGRESS_FILE}"
            echo "[worker-${WORKER_ID}] [${count}/${total}] GAVE UP after ${MAX_RETRIES} attempts: ${gav}"
        fi
    done
done < "${GAVS_FILE}"

echo "[worker-${WORKER_ID}] Finished all ${total} GAVs at $(date)"

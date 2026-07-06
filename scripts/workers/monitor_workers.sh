#!/usr/bin/env bash
# Monitor all worker tmux sessions and optionally auto-restart dead ones.
# Usage: monitor_workers.sh [--auto-restart]
#
# Configuration: set DATABASE_URL, NUM_WORKERS in .env (see .env.example).
# Requires: project .venv with buildroot installed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

# Load .env
ENV_FILE="${PROJECT_DIR}/.env"
[ -f "${ENV_FILE}" ] && set -a && source "${ENV_FILE}" && set +a

NUM_WORKERS="${NUM_WORKERS:-30}"
DATABASE_URL="${DATABASE_URL:-postgresql:///postgres}"
AUTO_RESTART="${1:-}"
STALE_THRESHOLD=1800  # 30 minutes

now=$(date +%s)

printf "\n%-8s %-10s %6s/%6s  %-20s  %s\n" "WORKER" "STATUS" "DONE" "TOTAL" "LAST ACTIVITY" "CURRENT GAV"
printf "%-8s %-10s %6s/%6s  %-20s  %s\n" "------" "------" "----" "-----" "-------------" "-----------"

total_done=0
total_gavs=0

for i in $(seq 0 $((NUM_WORKERS - 1))); do
    session_name="gx-build-reconstructor-worker-${i}"
    gavs_file="${PROJECT_DIR}/gavs/worker-${i}.txt"
    progress_file="${PROJECT_DIR}/logs/worker-${i}/progress.csv"
    log_dir="${PROJECT_DIR}/logs/worker-${i}"

    if [[ ! -f "${gavs_file}" ]]; then
        printf "%-8s %-10s %6s/%6s  %-20s  %s\n" "w-${i}" "NO GAVS" "0" "0" "-" "-"
        continue
    fi

    worker_total=$(wc -l < "${gavs_file}" | tr -d ' ')
    total_gavs=$((total_gavs + worker_total))

    if [[ -f "${progress_file}" ]]; then
        done_count=$(( $(wc -l < "${progress_file}" | tr -d ' ') - 1 ))
        [[ ${done_count} -lt 0 ]] && done_count=0
    else
        done_count=0
    fi
    total_done=$((total_done + done_count))

    mkdir -p "${log_dir}"
    last_log=$(find "${log_dir}" -name '*.log' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1)
    if [[ -n "${last_log}" ]]; then
        last_ts=$(echo "${last_log}" | awk '{printf "%d", $1}')
        age=$((now - last_ts))
        last_activity="$(date -d @"${last_ts}" '+%H:%M:%S') (${age}s ago)"
    else
        last_ts=0
        age=999999
        last_activity="no logs"
    fi

    current_gav="-"
    if [[ -f "${progress_file}" ]] && [[ ${done_count} -gt 0 ]]; then
        current_gav=$(tail -1 "${progress_file}" | cut -d',' -f1)
    fi

    if tmux has-session -t "${session_name}" 2>/dev/null; then
        if [[ ${age} -gt ${STALE_THRESHOLD} && ${done_count} -lt ${worker_total} ]]; then
            status="STUCK"
        else
            status="RUNNING"
        fi
    else
        if [[ ${done_count} -ge ${worker_total} && ${worker_total} -gt 0 ]]; then
            status="FINISHED"
        else
            status="DEAD"
        fi
    fi

    printf "%-8s %-10s %6d/%6d  %-20s  %s\n" \
        "w-${i}" "${status}" "${done_count}" "${worker_total}" "${last_activity}" "${current_gav}"

    if [[ "${AUTO_RESTART}" == "--auto-restart" && "${status}" == "DEAD" && ${done_count} -lt ${worker_total} ]]; then
        echo "  -> Restarting worker-${i} (${done_count}/${worker_total} done)"
        tmux new-session -d -s "${session_name}" -c "${PROJECT_DIR}" \
            "${SCRIPT_DIR}/run_worker.sh ${i} ${gavs_file}"
    fi
done

echo ""
echo "Total: ${total_done}/${total_gavs} builds complete"

db_total=$(${VENV_PYTHON} -c "
import psycopg2
conn = psycopg2.connect('${DATABASE_URL}')
cur = conn.cursor()
cur.execute('SELECT COUNT(*), COUNT(*) FILTER (WHERE reward >= 0.98) FROM builds')
total, l4 = cur.fetchone()
conn.close()
print(f'DB: {total} total builds, {l4} at L4 (reward >= 0.98)')
" 2>/dev/null || echo "DB: unavailable")
echo "${db_total}"

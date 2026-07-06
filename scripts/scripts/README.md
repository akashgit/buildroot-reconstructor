# Batch Worker Scripts

These scripts run the buildroot agent across hundreds of Maven coordinates in parallel using tmux sessions.

## Setup

1. Copy `.env.example` to `.env` at the project root and fill in values for your machine:

```bash
cp .env.example .env
```

2. Edit `.env` with your machine's values:

```bash
# On lw-preserve (local Postgres):
DATABASE_URL=postgresql:///postgres
DB_PYTHON=/home/lab/.local/share/uv/tools/buildroot/bin/python
NUM_WORKERS=30
GAVS_CSV_PATH=/workspace/shared/packages_remaining.csv

# On remote workers (lw2, lw3, lw4):
DATABASE_URL=postgresql://lab:instructlab@10.241.65.8/postgres
DB_PYTHON=/home/lab/.local/share/uv/tools/buildroot/bin/python
NUM_WORKERS=10
GAVS_CSV_PATH=/workspace/shared/packages_remaining.csv
```

## Scripts

### `launch_workers.sh`

Launches `NUM_WORKERS` parallel tmux sessions. Each session runs `run_worker.sh` on its assigned slice of GAVs.

```bash
./scripts/scripts/launch_workers.sh
```

What it does:
1. Runs `split_gavs.py` to distribute unprocessed GAVs across workers
2. Clears old log files
3. Pre-warms podman base images (one-time tarball)
4. Launches tmux sessions `gx-build-reconstructor-worker-0` through `worker-N`

### `run_worker.sh`

Processes GAVs sequentially from its assigned file. For each GAV:
1. Checks Postgres — skips if already built with reward >= 0.98
2. Runs `buildroot agent <gav> --enable-google-mirror`
3. Retries up to 3 times on failure
4. Logs progress to `logs/worker-N/progress.csv`

### `monitor_workers.sh`

Shows status of all workers in a table:

```bash
./scripts/scripts/monitor_workers.sh
```

```
WORKER   STATUS      DONE/ TOTAL  LAST ACTIVITY       CURRENT GAV
------   ------      ----/ -----  -------------       -----------
w-0      RUNNING       42/   156  14:23:01 (30s ago)  org.kie:kie-api:7.73.0.Final
w-1      RUNNING       38/   156  14:22:45 (46s ago)  org.jsoup:jsoup:1.18.1
w-2      DEAD          12/   156  13:50:22 (32m ago)  com.google.protobuf:protobuf-java:2.5.0
```

Auto-restart dead workers:
```bash
./scripts/scripts/monitor_workers.sh --auto-restart
```

### `split_gavs.py`

Reads GAVs from `GAVS_CSV_PATH`, excludes already-processed ones (from Postgres + progress logs), groups by artifact, and distributes across `NUM_WORKERS` balanced worker files in `gavs/`.

## Attaching to a worker

```bash
tmux attach -t gx-build-reconstructor-worker-0
```

Detach with `Ctrl-b d`.

#!/usr/bin/env python3
"""Extract GAVs from CSV, group by artifact, distribute across workers.

Configuration: set values in .env at the project root (see .env.example).
Required: GAVS_CSV_PATH, NUM_WORKERS
"""

import csv
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))
from buildroot.utils.dotenv import load_dotenv

load_dotenv(PROJECT_DIR / ".env")

NUM_WORKERS = int(os.environ.get("NUM_WORKERS", "30"))
CSV_PATH = Path(os.environ.get("GAVS_CSV_PATH", "/workspace/shared/packages_remaining.csv"))
OUTPUT_DIR = PROJECT_DIR / "gavs"


def get_processed_gavs():
    """Query DB + progress logs for already-attempted GAVs."""
    processed = set()

    db_url = os.environ.get("DATABASE_URL", "postgresql:///postgres")
    try:
        result = subprocess.run(
            ["psql", db_url, "-t", "-A", "-c",
             "SELECT group_id || ':' || artifact_id || ':' || version FROM builds"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                processed.add(line.strip())
    except Exception as e:
        print(f"WARNING: Could not query DB for processed GAVs: {e}", file=sys.stderr)

    log_dir = PROJECT_DIR / "logs"
    for progress_file in log_dir.glob("worker-*/progress.csv"):
        with open(progress_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("gav,"):
                    gav = line.split(",")[0]
                    if gav:
                        processed.add(gav)

    return processed


def main():
    if not CSV_PATH.exists():
        print(f"ERROR: GAVS_CSV_PATH not found: {CSV_PATH}", file=sys.stderr)
        print("Set GAVS_CSV_PATH in .env (see .env.example)", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    processed = get_processed_gavs()
    print(f"Already processed (in DB): {len(processed)}")

    all_gavs = []
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        content = f.read().replace("\r\n", "\n").replace("\r", "\n")

    for line in content.strip().split("\n")[1:]:
        row = next(csv.reader([line]))
        gav = row[-1].strip()
        parts = gav.split(":")
        if len(parts) == 3 and " " not in gav:
            all_gavs.append(gav)

    gavs = [g for g in all_gavs if g not in processed]
    print(f"Skipping {len(all_gavs) - len(gavs)} already-processed GAVs")

    groups = defaultdict(list)
    for gav in gavs:
        g, a, v = gav.split(":")
        groups[f"{g}:{a}"].append(gav)

    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    workers = [[] for _ in range(NUM_WORKERS)]
    worker_counts = [0] * NUM_WORKERS
    for key, group_gavs in sorted_groups:
        lightest = min(range(NUM_WORKERS), key=lambda i: worker_counts[i])
        workers[lightest].extend(group_gavs)
        worker_counts[lightest] += len(group_gavs)

    for i, worker_gavs in enumerate(workers):
        out = OUTPUT_DIR / f"worker-{i}.txt"
        out.write_text("\n".join(worker_gavs) + "\n")

    print(f"Total GAVs: {len(gavs)}")
    print(f"Artifact groups: {len(groups)}")
    print(f"Workers: {NUM_WORKERS}")
    for i, worker_gavs in enumerate(workers):
        print(f"  worker-{i}: {len(worker_gavs)} GAVs")


if __name__ == "__main__":
    main()

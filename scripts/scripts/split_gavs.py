#!/usr/bin/env python3
"""Extract GAVs from fixed CSV, group by artifact, distribute across workers."""

import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

NUM_WORKERS = 45
CSV_PATH = Path("/workspace/shared/packages_remaining_split_1_of_4.csv")
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "gavs"


def get_processed_gavs():
    """Query DB + progress logs for already-attempted GAVs."""
    processed = set()

    # From DB
    try:
        result = subprocess.run(
            ["psql", "-d", "postgres", "-t", "-A", "-c",
             "SELECT group_id || ':' || artifact_id || ':' || version FROM builds"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                processed.add(line.strip())
    except Exception as e:
        print(f"WARNING: Could not query DB for processed GAVs: {e}", file=sys.stderr)

    # From prior worker progress logs
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    processed = get_processed_gavs()
    print(f"Already processed (in DB): {len(processed)}")

    # Read all valid GAVs
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

    # Group by groupId:artifactId
    groups = defaultdict(list)
    for gav in gavs:
        g, a, v = gav.split(":")
        groups[f"{g}:{a}"].append(gav)

    # Assign artifact groups to workers, balancing by total GAV count
    # Sort groups largest-first, then greedily assign each to the lightest worker
    sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
    workers = [[] for _ in range(NUM_WORKERS)]
    worker_counts = [0] * NUM_WORKERS
    for key, group_gavs in sorted_groups:
        lightest = min(range(NUM_WORKERS), key=lambda i: worker_counts[i])
        workers[lightest].extend(group_gavs)
        worker_counts[lightest] += len(group_gavs)

    # Write worker files
    for i, worker_gavs in enumerate(workers):
        out = OUTPUT_DIR / f"worker-{i}.txt"
        out.write_text("\n".join(worker_gavs) + "\n")

    # Summary
    print(f"Total GAVs: {len(gavs)}")
    print(f"Artifact groups: {len(groups)}")
    print(f"Workers: {NUM_WORKERS}")
    for i, worker_gavs in enumerate(workers):
        print(f"  worker-{i}: {len(worker_gavs)} GAVs")


if __name__ == "__main__":
    main()

"""Hard test: does read latency degrade as the graph grows?

The DoD says read p95 should hold under 10x prod load. Latency-vs-size is
the cleanest measurement: load in batches, sample read p95 at each step.
If reads stay flat, indexes are healthy. If they grow linearly, the recursive
CTE or upsert path has a seq_scan somewhere.

Procedure:
  1. Optionally clear lineage_edge (--reset).
  2. For each step: generate `--batch` more events, load them, sample N
     random reads, measure p95.
  3. Print a CSV of (cumulative_edges, read_p95_ms, read_p99_ms).
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psycopg


def _edge_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM lineage_edge")
        row = cur.fetchone()
        assert row is not None
        return row[0]


def _reset(dsn: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE lineage_edge")
        conn.commit()


def _generate_and_load(target: str, batch_events: int, tmp_dir: Path) -> None:
    """Spawn generate.py to create a batch and load it (concurrency=8)."""
    fixture = tmp_dir / f"batch_{batch_events}_{int(time.time())}.ndjson"
    gen_script = Path(__file__).resolve().parents[1] / "fixtures" / "generate.py"
    edges = batch_events * 3
    subprocess.run(
        [sys.executable, str(gen_script), "--edges", str(edges), "--out", str(fixture)],
        check=True,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            sys.executable,
            str(gen_script),
            "--load",
            "--input",
            str(fixture),
            "--target",
            target,
            "--concurrency",
            "8",
        ],
        check=True,
        stderr=subprocess.DEVNULL,
    )
    fixture.unlink(missing_ok=True)


def _sample_reads(client: httpx.Client, target: str, samples: int, pool: int) -> list[float]:
    """Fire `samples` /direct queries against random URNs; return latencies in ms."""
    namespaces = [f"{i + 1}_ws_{(i + 1) * 7}" for i in range(20)]
    sources = [
        "facebook_ads",
        "google_ads",
        "tiktok_ads",
        "linkedin_ads",
        "snapchat_ads",
        "twitter_ads",
        "pinterest_ads",
        "amazon_ads",
        "criteo",
        "adroll",
    ]
    reports = ["campaigns", "adsets", "ads", "creatives", "insights"]

    def power_law(n: int, alpha: float = 1.5) -> int:
        return min(n - 1, int(n * (random.random() ** alpha)))

    latencies: list[float] = []
    for _ in range(samples):
        ns = namespaces[power_law(len(namespaces))]
        src = sources[power_law(len(sources))]
        rpt = reports[power_law(len(reports))]
        idx = power_law(pool)
        node = f"dataset:{ns}/{src}.api.{rpt}.{idx}"
        url = f"{target.rstrip('/')}/api/v1/lineage/direct?node={node}"
        t0 = time.time()
        r = client.get(url, timeout=10.0)
        latencies.append((time.time() - t0) * 1000)
        if r.status_code >= 400:
            print(f"  warn: read returned {r.status_code}", file=sys.stderr)
    return latencies


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="http://localhost:8000")
    ap.add_argument("--dsn", default="postgresql://lineage:lineage@localhost:5433/lineage")
    ap.add_argument("--reset", action="store_true", help="TRUNCATE before starting")
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument(
        "--batch-events", type=int, default=15_000, help="OL events per step (each ~3 edges)"
    )
    ap.add_argument("--samples-per-step", type=int, default=500)
    ap.add_argument("--out", type=Path, default=Path("benchmark/results/growing_graph.csv"))
    args = ap.parse_args()

    if args.reset:
        print("Resetting lineage_edge...")
        _reset(args.dsn)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path("benchmark/results/_tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[int, float, float, float]] = []
    print("step,cumulative_edges,read_p50_ms,read_p95_ms,read_p99_ms")
    print(f"--- starting (current rows: {_edge_count(args.dsn):,}) ---")

    with httpx.Client() as client:
        for step in range(1, args.steps + 1):
            t0 = time.time()
            _generate_and_load(args.target, args.batch_events, tmp_dir)
            load_s = time.time() - t0
            edges_now = _edge_count(args.dsn)

            # Match URN pool size to current dataset cardinality.
            pool = max(100, edges_now // 10)
            latencies = _sample_reads(client, args.target, args.samples_per_step, pool)
            latencies.sort()
            p50 = latencies[len(latencies) // 2]
            p95 = latencies[int(len(latencies) * 0.95)]
            p99 = latencies[int(len(latencies) * 0.99)]
            rows.append((edges_now, p50, p95, p99))
            print(
                f"step {step}/{args.steps}  edges={edges_now:>9,}  "
                f"loaded_in={load_s:5.1f}s  p50={p50:5.1f}  p95={p95:6.1f}  p99={p99:7.1f}"
            )

    with args.out.open("w") as f:
        f.write("cumulative_edges,p50_ms,p95_ms,p99_ms\n")
        for edges, p50, p95, p99 in rows:
            f.write(f"{edges},{p50:.2f},{p95:.2f},{p99:.2f}\n")

    print()
    print(f"CSV written -> {args.out}")
    # Pass criterion: read p95 at the final step must be within 3x of the first step.
    if len(rows) >= 2:
        first_p95 = rows[0][2]
        last_p95 = rows[-1][2]
        ratio = last_p95 / max(first_p95, 0.1)
        print(f"p95 growth ratio: {ratio:.2f}x  (first={first_p95:.1f}ms, last={last_p95:.1f}ms)")
        if ratio < 3.0:
            print("PASS: latency stays sub-3x as graph grows")
            return 0
        print("FAIL: latency grew more than 3x")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

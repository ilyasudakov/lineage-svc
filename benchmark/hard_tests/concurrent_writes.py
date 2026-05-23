"""Hard test: many producers writing the SAME edge simultaneously.

In prod, 4 DTS lineage workers can emit overlapping events when the same
table is extracted by multiple recipes. The DB-level guarantee we want:

  * exactly one row per (src_urn, dst_urn, edge_type)
  * zero client-visible errors (no leaked PK conflicts)
  * sustained writes during the storm

Procedure:
  1. Pick one OL event (one src → one dst → one job).
  2. Fire N threads x M repetitions, all POSTing that event.
  3. Query the DB directly via psycopg/asyncpg to count exact rows.
  4. Assert: 3 rows in lineage_edge (consumes + produces + derives_from);
     all client requests returned 2xx.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import psycopg

EVENT = {
    "eventType": "COMPLETE",
    "eventTime": "2026-05-23T00:00:00Z",
    "run": {"runId": "concurrent-test-run-A"},
    "job": {"namespace": "concurrent_test", "name": "concurrent.j1"},
    "inputs": [{"namespace": "concurrent_test", "name": "concurrent.input"}],
    "outputs": [{"namespace": "concurrent_test", "name": "concurrent.output"}],
}


def _post_one(client: httpx.Client, url: str) -> tuple[int, float]:
    t0 = time.time()
    r = client.post(url, content=json.dumps(EVENT), headers={"content-type": "application/json"})
    return r.status_code, (time.time() - t0) * 1000


def _count_rows(dsn: str) -> int:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM lineage_edge WHERE namespace = 'concurrent_test'")
        row = cur.fetchone()
        assert row is not None
        return row[0]


def _clear_rows(dsn: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lineage_edge WHERE namespace = 'concurrent_test'")
        conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="http://localhost:8000")
    ap.add_argument("--dsn", default="postgresql://lineage:lineage@localhost:5433/lineage")
    ap.add_argument("--threads", type=int, default=64)
    ap.add_argument("--reps", type=int, default=200, help="POSTs per thread")
    args = ap.parse_args()

    url = args.target.rstrip("/") + "/api/v1/lineage"

    print("Clearing previous test rows (namespace=concurrent_test)...")
    _clear_rows(args.dsn)
    assert _count_rows(args.dsn) == 0, "rows did not clear"

    total_posts = args.threads * args.reps
    print(f"Firing {args.threads} threads x {args.reps} reps = {total_posts:,} POSTs at {url}")
    latencies: list[float] = []
    errors: list[int] = []

    def worker() -> tuple[int, list[float]]:
        local_errors = 0
        local_latencies: list[float] = []
        with httpx.Client(timeout=30.0) as client:
            for _ in range(args.reps):
                code, latency = _post_one(client, url)
                local_latencies.append(latency)
                if code >= 400:
                    local_errors += 1
        return local_errors, local_latencies

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = [pool.submit(worker) for _ in range(args.threads)]
        for f in as_completed(futs):
            errs, lats = f.result()
            errors.append(errs)
            latencies.extend(lats)
    wall = time.time() - t0

    rows = _count_rows(args.dsn)
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    total_errors = sum(errors)

    print()
    print("=" * 60)
    print(f"  POSTs sent:        {total_posts:,}")
    print(f"  Wall time:         {wall:.2f}s")
    print(f"  Throughput:        {total_posts / wall:,.0f} POSTs/sec")
    print(f"  Client errors:     {total_errors}")
    print(f"  Latency p50/p95/p99: {p50:.1f} / {p95:.1f} / {p99:.1f} ms")
    print(f"  Rows in DB:        {rows} (expected: 3)")
    print("=" * 60)

    pk_unique = rows == 3
    no_errors = total_errors == 0
    ok = pk_unique and no_errors
    print("PASS" if ok else "FAIL")
    print(f"  exactly 3 rows:    {'OK' if pk_unique else 'FAIL'}")
    print(f"  zero client errors: {'OK' if no_errors else 'FAIL'}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

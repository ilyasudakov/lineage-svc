"""Synthetic OpenLineage event generator + loader.

Generates a power-law graph (a few hub datasets, long tail of leaves) at the
edge count specified, writes NDJSON of OL RunEvents to disk, and optionally
posts them against either lineage-svc or Marquez (same /api/v1/lineage shape).

Usage:
    # Generate fixture
    python generate.py --edges 5_000_000 --out fixture.ndjson

    # Load fixture into a target
    python generate.py --load --input fixture.ndjson --target http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx

NAMESPACES = [f"{i}_ws_{i * 7}" for i in range(1, 21)]  # 20 tenants
SOURCES = [
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
    "hubspot",
    "salesforce",
    "marketo",
    "pardot",
    "intercom",
]
REPORT_TYPES = ["campaigns", "adsets", "ads", "creatives", "insights", "audiences"]


def _power_law_pick(n: int, alpha: float = 1.5) -> int:
    """Zipf-like: small indices much more likely → hub nodes."""
    u = random.random()
    return min(n - 1, int(n * (u**alpha)))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _make_event(ns: str, job_idx: int, in_dataset_idx: int, out_dataset_idx: int) -> dict:
    source = SOURCES[job_idx % len(SOURCES)]
    report = REPORT_TYPES[(job_idx // len(SOURCES)) % len(REPORT_TYPES)]
    return {
        "eventType": "COMPLETE",
        "eventTime": _now_iso(),
        "producer": "https://github.com/improvado/dts",
        "run": {"runId": f"run-{ns}-{job_idx}-{random.randint(0, 10**9)}"},
        "job": {"namespace": ns, "name": f"extract.{source}.{report}.{job_idx}"},
        "inputs": [{"namespace": ns, "name": f"{source}.api.{report}.{in_dataset_idx}"}],
        "outputs": [
            {
                "namespace": ns,
                "name": f"data_table__{source}__{report}__sql_{out_dataset_idx}__{job_idx}",
            }
        ],
    }


def generate(edges: int, out_path: Path) -> None:
    """One OL event yields ~3 edges (consumes, produces, derives_from), so we
    emit `edges // 3` events to hit the target edge count."""
    events_to_emit = max(1, edges // 3)
    n_datasets = max(100, edges // 10)  # ensure reuse → power-law hubs
    print(
        f"Generating {events_to_emit:,} events → ~{edges:,} edges into {out_path}",
        file=sys.stderr,
    )
    t0 = time.time()
    with out_path.open("w", encoding="utf-8") as f:
        for job_idx in range(events_to_emit):
            ns = NAMESPACES[_power_law_pick(len(NAMESPACES))]
            in_idx = _power_law_pick(n_datasets)
            out_idx = _power_law_pick(n_datasets)
            f.write(json.dumps(_make_event(ns, job_idx, in_idx, out_idx)) + "\n")
            if job_idx and job_idx % 100_000 == 0:
                rate = job_idx / (time.time() - t0)
                print(f"  {job_idx:,} events ({rate:,.0f}/s)", file=sys.stderr)
    print(f"Done in {time.time() - t0:.1f}s", file=sys.stderr)


def _post_one(client: httpx.Client, url: str, line: str) -> int:
    r = client.post(url, content=line, headers={"content-type": "application/json"})
    return r.status_code


def load(target: str, input_path: Path, concurrency: int = 32) -> None:
    url = target.rstrip("/") + "/api/v1/lineage"
    print(f"Loading {input_path} → {url} (concurrency={concurrency})", file=sys.stderr)
    sent, errors = 0, 0
    t0 = time.time()
    with (
        httpx.Client(timeout=30.0, limits=httpx.Limits(max_connections=concurrency)) as client,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
        input_path.open("r", encoding="utf-8") as f,
    ):
        inflight: list = []
        for line in f:
            inflight.append(pool.submit(_post_one, client, url, line))
            if len(inflight) >= concurrency * 4:
                for fut in as_completed(inflight):
                    code = fut.result()
                    sent += 1
                    if code >= 400:
                        errors += 1
                    if sent % 10_000 == 0:
                        rate = sent / (time.time() - t0)
                        print(
                            f"  sent {sent:,} ({rate:,.0f}/s, errors={errors})",
                            file=sys.stderr,
                        )
                inflight = []
        for fut in as_completed(inflight):
            code = fut.result()
            sent += 1
            if code >= 400:
                errors += 1
    print(f"Loaded {sent:,} events in {time.time() - t0:.1f}s (errors={errors})", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edges", type=int, default=5_000_000, help="approx edge count (default 5M)")
    ap.add_argument("--out", type=Path, default=Path("fixture.ndjson"))
    ap.add_argument("--load", action="store_true", help="load NDJSON into --target")
    ap.add_argument("--input", type=Path, help="NDJSON file to load (used with --load)")
    ap.add_argument("--target", type=str, default="http://localhost:8000")
    ap.add_argument("--concurrency", type=int, default=32)
    args = ap.parse_args()

    if args.load:
        if not args.input:
            ap.error("--load requires --input")
        load(args.target, args.input, args.concurrency)
    else:
        generate(args.edges, args.out)


if __name__ == "__main__":
    main()

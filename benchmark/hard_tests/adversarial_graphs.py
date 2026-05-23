"""Hard test: graph topologies that stress the recursive CTE.

Three patterns:
  cycle   — A → B → C → A (lineage shouldn't have cycles, but bugs happen)
  deep    — linear chain of length N (depth=N traversal)
  wide    — one root → N children (high fanout, no recursion depth)

For each, we load edges directly via the API, then query at increasing
depths and observe latency / payload size / error.

Pass criteria (no DoD numbers — this is qualitative):
  * server doesn't crash, hang past 10s, or 5xx
  * cycle traversal terminates (no infinite recursion)
  * deep traversal at depth=100 returns within 5s
  * wide traversal returns the right edge count
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx
import psycopg


def _clear_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lineage_edge WHERE namespace = %s", (namespace,))
        conn.commit()


def _post_event(client: httpx.Client, target: str, event: dict) -> int:
    r = client.post(
        target.rstrip("/") + "/api/v1/lineage",
        content=json.dumps(event),
        headers={"content-type": "application/json"},
        timeout=10.0,
    )
    return r.status_code


def _read(client: httpx.Client, target: str, node: str, depth: int) -> tuple[int, int, float]:
    url = f"{target.rstrip('/')}/api/v1/lineage?node={node}&depth={depth}&direction=both"
    t0 = time.time()
    r = client.get(url, timeout=15.0)
    elapsed = (time.time() - t0) * 1000
    n_edges = len(r.json().get("edges", [])) if r.status_code == 200 else 0
    return r.status_code, n_edges, elapsed


def _make_event(ns: str, job: str, in_name: str, out_name: str, run: str) -> dict:
    return {
        "eventType": "COMPLETE",
        "eventTime": "2026-05-23T00:00:00Z",
        "run": {"runId": run},
        "job": {"namespace": ns, "name": job},
        "inputs": [{"namespace": ns, "name": in_name}],
        "outputs": [{"namespace": ns, "name": out_name}],
    }


def test_cycle(client: httpx.Client, target: str, dsn: str) -> bool:
    ns = "adv_cycle"
    _clear_namespace(dsn, ns)
    print(f"\n[cycle] loading 3-node cycle A->B->C->A in namespace={ns}")
    # A->B (job1), B->C (job2), C->A (job3). Three derives_from edges form a cycle.
    for i, (src, dst) in enumerate([("A", "B"), ("B", "C"), ("C", "A")]):
        code = _post_event(client, target, _make_event(ns, f"j{i}", src, dst, f"r{i}"))
        assert code in (200, 201), f"POST returned {code}"

    print("[cycle] traversing depth=10 from A (cycle should terminate)")
    code, n, ms = _read(client, target, f"dataset:{ns}/A", depth=10)
    print(f"        status={code} edges={n} latency={ms:.0f}ms")
    if code != 200 or ms > 10_000:
        print("        FAIL")
        return False
    print(f"        OK (cycle terminated, returned {n} edges)")
    return True


def test_deep(client: httpx.Client, target: str, dsn: str, length: int = 100) -> bool:
    ns = "adv_deep"
    _clear_namespace(dsn, ns)
    print(f"\n[deep] loading chain of length={length}")
    with httpx.Client(timeout=30.0) as c:
        for i in range(length):
            code = _post_event(c, target, _make_event(ns, f"j{i}", f"n{i}", f"n{i + 1}", f"r{i}"))
            assert code in (200, 201), f"POST {i} returned {code}"

    # API caps depth at 50 (deliberate guardrail in app/main.py); test at the cap.
    print(f"[deep] traversing depth=50 from n0 (chain length {length}, API cap)")
    code, n, ms = _read(client, target, f"dataset:{ns}/n0", depth=50)
    print(f"       status={code} edges={n} latency={ms:.0f}ms")
    if code != 200 or ms > 5_000:
        print("       FAIL")
        return False

    print("[deep] traversing depth=51 from n0 (above cap — should be rejected)")
    code, n, ms = _read(client, target, f"dataset:{ns}/n0", depth=51)
    print(f"       status={code} (expecting 422)")
    if code != 422:
        print(f"       FAIL: depth>50 should return 422, got {code}")
        return False
    print("       OK (guardrail held)")
    return True


def test_wide(client: httpx.Client, target: str, dsn: str, fanout: int = 1000) -> bool:
    ns = "adv_wide"
    _clear_namespace(dsn, ns)
    print(f"\n[wide] loading 1 root with fanout={fanout}")
    # One job that ingests "root" and emits 1000 outputs in one event.
    out = [{"namespace": ns, "name": f"leaf_{i}"} for i in range(fanout)]
    event = {
        "eventType": "COMPLETE",
        "eventTime": "2026-05-23T00:00:00Z",
        "run": {"runId": "wide-1"},
        "job": {"namespace": ns, "name": "fanout_job"},
        "inputs": [{"namespace": ns, "name": "root"}],
        "outputs": out,
    }
    code = _post_event(client, target, event)
    if code not in (200, 201):
        print(f"       POST returned {code} — FAIL")
        return False

    print(f"[wide] traversing depth=1 from root (should return ~{fanout * 2} edges)")
    code, n, ms = _read(client, target, f"dataset:{ns}/root", depth=1)
    print(f"       status={code} edges={n} latency={ms:.0f}ms")
    if code != 200:
        print("       FAIL")
        return False
    # Expect: 1 'consumes' edge (root -> job) and `fanout` 'derives_from' edges (root -> leaf_*)
    expected = 1 + fanout
    if n != expected:
        print(f"       FAIL: expected {expected} edges, got {n}")
        return False
    print("       OK")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="http://localhost:8000")
    ap.add_argument("--dsn", default="postgresql://lineage:lineage@localhost:5433/lineage")
    ap.add_argument("--deep-length", type=int, default=100)
    ap.add_argument("--wide-fanout", type=int, default=1000)
    args = ap.parse_args()

    results: list[tuple[str, bool]] = []
    with httpx.Client() as client:
        results.append(("cycle", test_cycle(client, args.target, args.dsn)))
        results.append(("deep", test_deep(client, args.target, args.dsn, args.deep_length)))
        results.append(("wide", test_wide(client, args.target, args.dsn, args.wide_fanout)))

    print("\n" + "=" * 60)
    for name, ok in results:
        print(f"  {name:8s} {'PASS' if ok else 'FAIL'}")
    print("=" * 60)
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())

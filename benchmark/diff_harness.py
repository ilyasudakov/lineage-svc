"""Edge-set equality diff between data-lineage and Marquez.

Picks N nodes randomly from a sample file (one URN per line) and for each one
queries the `direct` endpoint on both backends, then compares the upstream and
downstream edge sets (src, dst, edge_type) as sets. Reports mismatches.

Marquez does not expose the same `/api/v1/lineage/direct` shape, so the
adapter `marquez_direct()` translates Marquez's `/api/v1/lineage?nodeId=...&depth=1`
response into the same `(src, dst, edge_type)` tuple set.

Usage:
    python diff_harness.py \\
        --lineage http://localhost:8000 \\
        --marquez http://localhost:5000 \\
        --samples sample_nodes.txt \\
        --n 1000 \\
        --out diff_report.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import httpx

EdgeKey = tuple[str, str, str]


def lineage_direct(client: httpx.Client, base: str, node: str) -> set[EdgeKey]:
    r = client.get(f"{base}/api/v1/lineage/direct", params={"node": node})
    r.raise_for_status()
    body = r.json()
    edges: set[EdgeKey] = set()
    for e in body.get("upstream", []) + body.get("downstream", []):
        edges.add((e["src_urn"], e["dst_urn"], e["edge_type"]))
    return edges


def marquez_direct(client: httpx.Client, base: str, node: str) -> set[EdgeKey]:
    """Translate Marquez lineage response (graph of nodes+edges) into our tuple set.

    Marquez returns: {"graph": [{"id": "...", "type": "DATASET|JOB", "inEdges":[],
    "outEdges":[{"origin":"...","destination":"..."}]}, ...]}
    """
    r = client.get(f"{base}/api/v1/lineage", params={"nodeId": node, "depth": 1})
    r.raise_for_status()
    body = r.json()
    edges: set[EdgeKey] = set()
    for n in body.get("graph", []):
        n_type = n.get("type", "").lower()
        for e in n.get("outEdges", []):
            edge_type = "produces" if n_type == "job" else "consumes"
            edges.add((e["origin"], e["destination"], edge_type))
    return edges


def diff_one(client: httpx.Client, lineage_base: str, marquez_base: str, node: str) -> dict | None:
    """Return mismatch detail, or None if edge sets are equal."""
    try:
        a = lineage_direct(client, lineage_base, node)
        b = marquez_direct(client, marquez_base, node)
    except httpx.HTTPError as exc:
        return {"node": node, "error": str(exc)}
    if a == b:
        return None
    return {
        "node": node,
        "only_in_lineage_svc": sorted(a - b),
        "only_in_marquez": sorted(b - a),
    }


def run(args: argparse.Namespace) -> int:
    sample_lines = [line.strip() for line in args.samples.read_text().splitlines() if line.strip()]
    if not sample_lines:
        print("sample file is empty", file=sys.stderr)
        return 2
    nodes = random.sample(sample_lines, min(args.n, len(sample_lines)))

    mismatches: list[dict] = []
    counts = Counter({"checked": 0, "match": 0, "mismatch": 0, "error": 0})

    with httpx.Client(timeout=30.0) as client:
        for i, node in enumerate(nodes, 1):
            res = diff_one(client, args.lineage, args.marquez, node)
            counts["checked"] += 1
            if res is None:
                counts["match"] += 1
            elif "error" in res:
                counts["error"] += 1
                mismatches.append(res)
            else:
                counts["mismatch"] += 1
                mismatches.append(res)
            if i % 100 == 0:
                print(f"  {i}/{len(nodes)}  {dict(counts)}", file=sys.stderr)

    report = {
        "lineage_base": args.lineage,
        "marquez_base": args.marquez,
        "summary": dict(counts),
        "match_rate": counts["match"] / max(1, counts["checked"]),
        "mismatches": mismatches,
    }
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"], indent=2))
    return 0 if counts["mismatch"] == 0 and counts["error"] == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lineage", default="http://localhost:8000")
    ap.add_argument("--marquez", default="http://localhost:5000")
    ap.add_argument("--samples", type=Path, required=True, help="text file, one URN per line")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=Path("diff_report.json"))
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()

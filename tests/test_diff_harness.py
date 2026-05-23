"""Unit tests for diff_harness response adapters.

Network calls are not exercised here — we test that the parse logic produces
correct `(src, dst, edge_type)` tuples from the two response shapes.
"""

import sys
from pathlib import Path

import httpx

# benchmark/ is not a Python package; add to path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))

from diff_harness import lineage_direct, marquez_direct


def _client_with(body: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lineage_direct_parses_upstream_and_downstream():
    body = {
        "node": "x",
        "upstream": [{"src_urn": "a", "dst_urn": "x", "edge_type": "produces"}],
        "downstream": [{"src_urn": "x", "dst_urn": "b", "edge_type": "produces"}],
    }
    with _client_with(body) as c:
        result = lineage_direct(c, "http://t", "x")
    assert result == {("a", "x", "produces"), ("x", "b", "produces")}


def test_marquez_direct_translates_graph_to_edge_tuples():
    body = {
        "graph": [
            {
                "id": "dataset:a",
                "type": "DATASET",
                "outEdges": [{"origin": "dataset:a", "destination": "job:j"}],
            },
            {
                "id": "job:j",
                "type": "JOB",
                "outEdges": [{"origin": "job:j", "destination": "dataset:b"}],
            },
        ]
    }
    with _client_with(body) as c:
        result = marquez_direct(c, "http://t", "x")
    assert result == {
        ("dataset:a", "job:j", "consumes"),
        ("job:j", "dataset:b", "produces"),
    }

"""Translate OpenLineage RunEvent → lineage_edge rows.

PoC scope (IMD-60352): table-level lineage only. Three edge shapes:
  - inputs[i] --consumes--> job  (with job_urn=job, run_id)
  - job --produces--> outputs[j]
  - inputs[i] --derives_from--> outputs[j]  (denormalized for fast direct lookup)

DTS emits three event flavors — Extract, Load, Transform. All share the same
OL RunEvent shape with `inputs` and `outputs` populated. Transform events
additionally carry `TransformMetadataJobFacet.source_tables` on the job facets;
when standard `inputs` is empty, we fall back to that.
"""

from app.schemas import Edge, OpenLineageEvent


def _dataset_urn(ns: str, name: str) -> str:
    return f"dataset:{ns}/{name}"


def _job_urn(ns: str, name: str) -> str:
    return f"job:{ns}/{name}"


def _transform_source_tables(event: OpenLineageEvent) -> list[dict]:
    """Pull source_tables out of DTS' custom TransformMetadataJobFacet, if present."""
    facets = (event.job or {}).get("facets") or {}
    facet = facets.get("transformMetadata") or facets.get("TransformMetadataJobFacet") or {}
    tables = facet.get("source_tables") or []
    return [t for t in tables if isinstance(t, dict) and t.get("name")]


def _dedupe(edges: list[Edge]) -> list[Edge]:
    """Within a single event, collapse duplicate (src, dst, type) tuples.

    DB upsert handles cross-event dedup; this keeps the batch clean so
    upsert_edges sees no internal conflicts and write counts are accurate.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[Edge] = []
    for e in edges:
        key = (e.src_urn, e.dst_urn, e.edge_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def translate(event: OpenLineageEvent) -> list[Edge]:
    job_ns = event.job.get("namespace", "default")
    job_name = event.job.get("name", "unknown")
    job_urn = _job_urn(job_ns, job_name)
    run_id = (event.run or {}).get("runId")
    namespace = job_ns

    inputs = event.inputs or _transform_source_tables(event)
    in_urns = [_dataset_urn(i.get("namespace", job_ns), i["name"]) for i in inputs if i.get("name")]
    out_urns = [
        _dataset_urn(o.get("namespace", job_ns), o["name"])
        for o in (event.outputs or [])
        if o.get("name")
    ]

    edges: list[Edge] = []
    for src in in_urns:
        edges.append(
            Edge(
                src_urn=src,
                dst_urn=job_urn,
                edge_type="consumes",
                job_urn=job_urn,
                run_id=run_id,
                namespace=namespace,
            )
        )
    for dst in out_urns:
        edges.append(
            Edge(
                src_urn=job_urn,
                dst_urn=dst,
                edge_type="produces",
                job_urn=job_urn,
                run_id=run_id,
                namespace=namespace,
            )
        )
    for src in in_urns:
        for dst in out_urns:
            edges.append(
                Edge(
                    src_urn=src,
                    dst_urn=dst,
                    edge_type="derives_from",
                    job_urn=job_urn,
                    run_id=run_id,
                    namespace=namespace,
                )
            )
    return _dedupe(edges)

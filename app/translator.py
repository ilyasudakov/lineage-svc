"""Translate OpenLineage RunEvent → lineage_edge rows.

For PoC: only table-level lineage. Three edge shapes:
  - inputs[i] --consumes--> job  (with job_urn=job, run_id)
  - job --produces--> outputs[j]
  - inputs[i] --derives_from--> outputs[j]  (denormalized for fast direct lookup)
"""

from app.schemas import Edge, OpenLineageEvent


def _dataset_urn(ns: str, name: str) -> str:
    return f"dataset:{ns}/{name}"


def _job_urn(ns: str, name: str) -> str:
    return f"job:{ns}/{name}"


def translate(event: OpenLineageEvent) -> list[Edge]:
    job_ns = event.job.get("namespace", "default")
    job_name = event.job.get("name", "unknown")
    job_urn = _job_urn(job_ns, job_name)
    run_id = (event.run or {}).get("runId")
    namespace = job_ns

    edges: list[Edge] = []
    in_urns = [_dataset_urn(i.get("namespace", job_ns), i["name"]) for i in event.inputs if i.get("name")]
    out_urns = [_dataset_urn(o.get("namespace", job_ns), o["name"]) for o in event.outputs if o.get("name")]

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

    return edges

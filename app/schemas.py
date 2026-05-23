from typing import Any, Literal

from pydantic import BaseModel, Field

EdgeType = Literal["produces", "consumes", "derives_from"]
Direction = Literal["upstream", "downstream", "both"]


class Edge(BaseModel):
    src_urn: str
    dst_urn: str
    edge_type: EdgeType
    job_urn: str | None = None
    run_id: str | None = None
    namespace: str
    metadata: dict[str, Any] | None = None


class LineageNeighbors(BaseModel):
    node: str
    upstream: list[Edge] = Field(default_factory=list)
    downstream: list[Edge] = Field(default_factory=list)


class OpenLineageEvent(BaseModel):
    """Subset of OpenLineage RunEvent. Producers post these unchanged."""

    eventType: str
    eventTime: str
    run: dict[str, Any]
    job: dict[str, Any]
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    producer: str | None = None

    model_config = {"extra": "allow"}

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LineageEdge(Base):
    __tablename__ = "lineage_edge"

    src_urn: Mapped[str] = mapped_column(String, primary_key=True)
    dst_urn: Mapped[str] = mapped_column(String, primary_key=True)
    edge_type: Mapped[str] = mapped_column(String, primary_key=True)
    job_urn: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    namespace: Mapped[str] = mapped_column(String, nullable=False)
    edge_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB().with_variant(JSON, "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_lineage_edge_src_urn", "src_urn"),
        Index("ix_lineage_edge_dst_urn", "dst_urn"),
        Index("ix_lineage_edge_job_urn", "job_urn"),
        Index("ix_lineage_edge_namespace", "namespace"),
    )

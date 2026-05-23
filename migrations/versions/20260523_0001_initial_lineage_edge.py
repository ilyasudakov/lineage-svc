"""initial lineage_edge

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lineage_edge",
        sa.Column("src_urn", sa.Text(), nullable=False),
        sa.Column("dst_urn", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),
        sa.Column("job_urn", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("src_urn", "dst_urn", "edge_type"),
    )
    op.create_index("ix_lineage_edge_src_urn", "lineage_edge", ["src_urn"])
    op.create_index("ix_lineage_edge_dst_urn", "lineage_edge", ["dst_urn"])
    op.create_index("ix_lineage_edge_job_urn", "lineage_edge", ["job_urn"])
    op.create_index("ix_lineage_edge_namespace", "lineage_edge", ["namespace"])


def downgrade() -> None:
    op.drop_index("ix_lineage_edge_namespace", table_name="lineage_edge")
    op.drop_index("ix_lineage_edge_job_urn", table_name="lineage_edge")
    op.drop_index("ix_lineage_edge_dst_urn", table_name="lineage_edge")
    op.drop_index("ix_lineage_edge_src_urn", table_name="lineage_edge")
    op.drop_table("lineage_edge")

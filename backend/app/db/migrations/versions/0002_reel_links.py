from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_reel_links"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reel_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("page_file", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_reel_links_slug"),
    )
    op.create_index("idx_reel_links_enabled_order", "reel_links", ["enabled", "sort_order"])

    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            "reel_links",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("slug", sa.String),
            sa.column("title", sa.String),
            sa.column("page_file", sa.String),
            sa.column("url", sa.Text),
            sa.column("image_count", sa.Integer),
            sa.column("sort_order", sa.Integer),
            sa.column("enabled", sa.Boolean),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": uuid.uuid4(),
                "slug": "viewer-1",
                "title": "Trang 1 — image",
                "page_file": "viewer.html",
                "url": "/reels/viewer-1",
                "image_count": 7,
                "sort_order": 1,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "slug": "viewer-2",
                "title": "Trang 2 — image2",
                "page_file": "viewer2.html",
                "url": "/reels/viewer-2",
                "image_count": 7,
                "sort_order": 2,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_reel_links_enabled_order", table_name="reel_links")
    op.drop_table("reel_links")

"""마감 임박 알림 기록

Revision ID: 730a69612ba2
Revises: 02cdcdba877a
Create Date: 2026-08-19 05:37:28.591502
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '730a69612ba2'
down_revision: str | None = '02cdcdba877a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('markets', sa.Column('closing_soon_notified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('markets', 'closing_soon_notified_at')

"""주문 체결 시각 컬럼

Revision ID: 02cdcdba877a
Revises: ceb82ba90f94
Create Date: 2026-08-19 05:29:53.371773
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '02cdcdba877a'
down_revision: str | None = 'ceb82ba90f94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('filled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'last_synced_at')
    op.drop_column('orders', 'filled_at')

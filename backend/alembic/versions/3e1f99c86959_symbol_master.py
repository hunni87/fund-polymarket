"""종목 마스터 테이블

Revision ID: 3e1f99c86959
Revises: 730a69612ba2
Create Date: 2026-08-19 05:41:54.451081
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '3e1f99c86959'
down_revision: str | None = '730a69612ba2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('symbols',
    sa.Column('ticker', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('market', sa.String(length=20), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('ticker')
    )
    op.create_index(op.f('ix_symbols_name'), 'symbols', ['name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_symbols_name'), table_name='symbols')
    op.drop_table('symbols')

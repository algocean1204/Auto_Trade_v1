# [DEPRECATED] PostgreSQL 전용 마이그레이션 -- SQLite 환경에서는 사용하지 않는다.
# 0004_sqlite_initial.py를 단독 initial migration으로 사용한다.
# 이 파일은 PostgreSQL 백업/참고용으로만 보관한다.
"""유니버스 설정 테이블을 추가한다.

universe_config 테이블은 ETF 유니버스 티커 설정의 source of truth이다.
부팅 시 DB가 비어있으면 하드코딩 _ETF_RAW 데이터로 시드한다.

Revision ID: 0002
Revises: 0001_v2_clean
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# ── 리비전 식별자 ──
revision: str = "0002"
down_revision: Union[str, None] = "0001_v2_clean"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """universe_config 테이블을 생성한다.

    Integer PK (auto-increment), ticker UNIQUE 제약, updated_at onupdate를 포함한다.
    """
    op.create_table(
        "universe_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False, server_default="AMS"),
        sa.Column("sector", sa.String(50), nullable=False, server_default="broad_market"),
        sa.Column("leverage", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("is_inverse", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pair_ticker", sa.String(20), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", name="uq_universe_config_ticker"),
    )
    # 티커 검색에 사용하는 인덱스이다
    op.create_index("ix_universe_config_ticker", "universe_config", ["ticker"], unique=True)
    # 활성 티커만 필터링하는 용도이다
    op.create_index("ix_universe_config_enabled", "universe_config", ["enabled"], unique=False)


def downgrade() -> None:
    """universe_config 테이블을 삭제한다."""
    op.drop_index("ix_universe_config_enabled", table_name="universe_config")
    op.drop_index("ix_universe_config_ticker", table_name="universe_config")
    op.drop_table("universe_config")

# [DEPRECATED] PostgreSQL 전용 마이그레이션 -- SQLite 환경에서는 사용하지 않는다.
# 0004_sqlite_initial.py를 단독 initial migration으로 사용한다.
# 이 파일은 PostgreSQL 백업/참고용으로만 보관한다.
"""V1 articles 테이블을 V2 스키마로 교체한다.

V1 스키마(headline, language, tickers_mentioned 등)가 잔존하여
V2 ORM 모델(title, direction, category 등)과 불일치하는 문제를 수정한다.
기존 V1 데이터(235건)는 폐기한다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# ── 리비전 식별자 ──
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """V1 articles 테이블을 삭제하고 V2 스키마로 재생성한다."""
    # V1 인덱스 삭제 (존재할 경우)
    op.execute("DROP INDEX IF EXISTS idx_articles_content_hash")
    op.execute("DROP INDEX IF EXISTS idx_articles_is_processed")
    op.execute("DROP INDEX IF EXISTS idx_articles_published_at")
    op.execute("DROP INDEX IF EXISTS idx_articles_source_crawled")

    # V1 테이블 삭제
    op.drop_table("articles")

    # V2 스키마로 재생성
    op.create_table(
        "articles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_articles_url"),
    )
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"], unique=False)
    op.create_index("ix_articles_published_at", "articles", ["published_at"], unique=False)


def downgrade() -> None:
    """V2 articles 테이블을 삭제한다. V1 복원은 지원하지 않는다."""
    op.drop_index("ix_articles_published_at", table_name="articles")
    op.drop_index("ix_articles_content_hash", table_name="articles")
    op.drop_table("articles")

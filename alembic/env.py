"""Alembic 마이그레이션 환경 설정이다. SQLite(aiosqlite) 기반으로 동작한다."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 프로젝트 루트를 sys.path에 추가한다
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def get_url() -> str:
    """DATABASE_URL 환경변수에서 DB URL을 구성한다.

    SQLite 기반이므로 aiosqlite → sqlite 동기 드라이버로 변환한다.
    Alembic은 동기 드라이버만 지원하기 때문이다.
    """
    from dotenv import load_dotenv
    load_dotenv()

    url = os.getenv("DATABASE_URL", "sqlite:///data/trading.db")

    # aiosqlite → sqlite 변환 (Alembic은 동기 드라이버 사용)
    url = url.replace("sqlite+aiosqlite", "sqlite")

    return url

def run_migrations_offline() -> None:
    """오프라인 모드로 마이그레이션을 실행한다."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite는 ALTER TABLE 제한이 있으므로 batch 모드 사용
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """온라인 모드로 마이그레이션을 실행한다."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite는 ALTER TABLE 제한이 있으므로 batch 모드 사용
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

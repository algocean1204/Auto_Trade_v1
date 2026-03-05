"""Alembic 마이그레이션 환경 설정이다."""
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
    """DATABASE_URL 또는 개별 DB_* 환경변수에서 DB URL을 구성한다.

    SecretVault의 _build_composite_secrets()와 동일한 로직이다.
    Alembic은 동기 드라이버(psycopg2)를 사용하므로 asyncpg를 변환한다.
    """
    from dotenv import load_dotenv
    load_dotenv()

    url = os.getenv("DATABASE_URL", "")
    if not url:
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        user = os.getenv("DB_USER", "trading")
        pw = os.getenv("DB_PASSWORD", "")
        name = os.getenv("DB_NAME", "trading_system")
        url = f"postgresql+asyncpg://{user}:{pw}@{host}:{port}/{name}"

    # asyncpg -> psycopg2 변환 (Alembic은 동기 드라이버 사용)
    return url.replace("+asyncpg", "+psycopg2").replace("postgresql://", "postgresql+psycopg2://")

def run_migrations_offline() -> None:
    """오프라인 모드로 마이그레이션을 실행한다."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

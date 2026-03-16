"""PostgreSQL → SQLite 데이터 마이그레이션 스크립트이다.

기존 Docker PostgreSQL 모든 테이블을 SQLite로 이관한다. 1회성 스크립트이다.

사용법:
    python scripts/migrate_pg_to_sqlite.py [--pg-url URL] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.common.database_gateway import Base
from src.db import models  # noqa: F401 -- ORM 모델을 Base.metadata에 등록한다

_DATA_DIR = _PROJECT_ROOT / "data"
_SQLITE_PATH = _DATA_DIR / "trading.db"
_ENV_FILE = _PROJECT_ROOT / ".env"
_BATCH_SIZE = 500

# 이관 대상 27개 테이블 -- 외래 키 없는 독립 테이블이므로 순서 제약이 없다
_TABLES = [
    "articles", "trades", "etf_universe", "indicator_history",
    "strategy_param_history", "feedback_reports", "crawl_checkpoints",
    "pending_adjustments", "tax_records", "fx_rates", "slippage_log",
    "emergency_events", "benchmark_snapshots", "capital_guard_log",
    "notification_log", "profit_targets", "daily_pnl_log", "risk_config",
    "risk_events", "backtest_results", "fear_greed_history",
    "prediction_markets", "historical_analyses", "historical_analysis_progress",
    "tick_data", "rag_documents", "universe_config",
]


def _load_env() -> dict[str, str]:
    """환경변수를 .env 파일에서 로드한다. 파일이 없으면 빈 dict를 반환한다."""
    env: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return env
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.split("#")[0].strip()
    return env


def _build_pg_url(env: dict[str, str]) -> str:
    """환경변수에서 PostgreSQL psycopg2 URL을 조합한다."""
    if "DATABASE_URL" in env:
        return (
            env["DATABASE_URL"]
            .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            .replace("postgresql://", "postgresql+psycopg2://")
        )
    h = env.get("DB_HOST", "localhost")
    p = env.get("DB_PORT", "5432")
    u = env.get("DB_USER", "trading")
    pw = env.get("DB_PASSWORD", "")
    n = env.get("DB_NAME", "trading_system")
    return f"postgresql+psycopg2://{u}:{pw}@{h}:{p}/{n}"


def _to_sqlite_val(val: object) -> object:
    """PostgreSQL 값을 SQLite 저장 가능 형태로 변환한다. datetime→ISO8601, dict/list→JSON, UUID→str이다."""
    import uuid as _uuid_mod
    if isinstance(val, _uuid_mod.UUID):
        return str(val)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.isoformat()
    if isinstance(val, (dict, list)):
        return json.dumps(val, default=str, ensure_ascii=False)
    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()
    return val


def _migrate_table(pg_sess: Session, sq_sess: Session, tbl: str, force: bool) -> int:
    """단일 테이블을 PostgreSQL → SQLite로 배치 이관한다. 이관된 행 수를 반환한다."""
    existing: int = sq_sess.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar_one()
    if existing > 0 and not force:
        print(f"  [SKIP] {tbl}: SQLite에 {existing}행 존재 (--force로 덮어쓰기)")
        return 0
    if existing > 0 and force:
        sq_sess.execute(text(f"DELETE FROM {tbl}"))
        sq_sess.commit()

    columns = [c["name"] for c in inspect(pg_sess.bind).get_columns(tbl)]
    col_sql = ", ".join(columns)
    ph_sql = ", ".join(f":{c}" for c in columns)
    insert_q = text(f"INSERT OR REPLACE INTO {tbl} ({col_sql}) VALUES ({ph_sql})")
    total: int = pg_sess.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar_one()

    migrated, offset = 0, 0
    while offset < total:
        rows = pg_sess.execute(
            text(f"SELECT {col_sql} FROM {tbl} LIMIT :lim OFFSET :off"),
            {"lim": _BATCH_SIZE, "off": offset},
        ).fetchall()
        if not rows:
            break
        batch = [{c: _to_sqlite_val(v) for c, v in zip(columns, row)} for row in rows]
        sq_sess.execute(insert_q, batch)
        sq_sess.commit()
        migrated += len(batch)
        offset += _BATCH_SIZE
        print(f"  {tbl}: {migrated}/{total}", end="\r")

    print(f"  [OK] {tbl}: {migrated}/{total} 행                    ")
    return migrated


def _count(sess: Session, tbl: str) -> int:
    """테이블 행 수를 반환한다. 오류 시 -1을 반환한다."""
    try:
        return sess.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar_one()
    except Exception:
        return -1


def main() -> None:
    """마이그레이션 메인 진입점이다."""
    parser = argparse.ArgumentParser(description="PostgreSQL → SQLite 마이그레이션")
    parser.add_argument("--pg-url", help="PostgreSQL URL (미지정 시 .env에서 읽음)")
    parser.add_argument("--force", action="store_true", help="기존 SQLite 데이터 덮어쓰기")
    args = parser.parse_args()

    # 1) PostgreSQL 연결
    pg_url = args.pg_url or _build_pg_url(_load_env())
    print(f"\n[1/5] PostgreSQL 연결: {pg_url.split('@')[-1]}")
    try:
        pg_engine = create_engine(pg_url, pool_pre_ping=True)
        pg_engine.connect().close()
        print("  연결 성공")
    except Exception as exc:
        print(f"  [ERROR] PostgreSQL 연결 실패: {exc}")
        sys.exit(1)

    # 2) SQLite 초기화 -- WAL 모드 활성화 후 ORM 스키마 생성
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    sq_url = f"sqlite:///{_SQLITE_PATH}"
    print(f"\n[2/5] SQLite 초기화: {_SQLITE_PATH}")
    try:
        sq_engine = create_engine(sq_url, echo=False)
        with sq_engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA foreign_keys=OFF"))
        Base.metadata.create_all(sq_engine)
        print("  스키마 생성/확인 완료")
    except Exception as exc:
        print(f"  [ERROR] SQLite 초기화 실패: {exc}")
        sys.exit(1)

    # 3) 테이블 순회 이관
    print(f"\n[3/5] 이관 시작 (총 {len(_TABLES)}개 테이블)")
    results: dict[str, int] = {}
    with Session(pg_engine) as pg_s, Session(sq_engine) as sq_s:
        for tbl in _TABLES:
            try:
                results[tbl] = _migrate_table(pg_s, sq_s, tbl, args.force)
            except Exception as exc:
                print(f"  [ERROR] {tbl} 이관 실패: {exc}")
                results[tbl] = -1

    # 4) row count 검증
    print("\n[4/5] Row count 검증")
    mismatch: list[str] = []
    with Session(pg_engine) as pg_s, Session(sq_engine) as sq_s:
        for tbl in _TABLES:
            pg_n, sq_n = _count(pg_s, tbl), _count(sq_s, tbl)
            ok = pg_n == sq_n
            if not ok:
                mismatch.append(tbl)
            print(f"  [{'OK' if ok else 'MISMATCH'}] {tbl}: PG={pg_n}, SQLite={sq_n}")

    # 5) 결과 요약
    failed = [t for t, v in results.items() if v < 0]
    total_rows = sum(v for v in results.values() if v > 0)
    print(f"\n[5/5] 요약  총 이관 행: {total_rows:,} | 실패: {len(failed)} | 불일치: {len(mismatch)}")
    if failed:
        print(f"  실패 테이블: {failed}")
    if mismatch:
        print(f"  불일치 테이블: {mismatch}")
    print(f"  SQLite 경로: {_SQLITE_PATH}")

    if failed or mismatch:
        print("\n  [WARNING] 일부 테이블에 문제가 있다. 위 목록을 확인하라.")
        sys.exit(1)
    print("\n  [SUCCESS] 이관 완료. Docker PostgreSQL을 안전하게 제거할 수 있다.")


if __name__ == "__main__":
    main()

"""세금 관련 캐시 기록 — EOD 시퀀스에서 호출하여 세금 현황을 갱신한다.

tax.py 엔드포인트가 읽는 tax:status, tax:report:{year}, tax:harvest 캐시 키를
DB의 trades 테이블과 현재 포지션 데이터로부터 계산하여 기록한다.

한국 해외주식 양도소득세: (양도차익 - 250만원 기본공제) × 22% (지방소득세 포함)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.common.cache_gateway import CacheClient
from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger

_logger = get_logger(__name__)

# 한국 양도소득세 상수이다
_ANNUAL_EXEMPTION_KRW: int = 2_500_000
_TAX_RATE: float = 0.22
_DEFAULT_FX_RATE: float = 1350.0


async def _get_fx_rate(cache: CacheClient) -> float:
    """macro:DEXKOUS 캐시에서 최신 USD/KRW 환율을 읽는다. 없으면 기본값을 반환한다."""
    data = await cache.read_json("macro:DEXKOUS")
    if data and isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            try:
                return float(first.get("value", _DEFAULT_FX_RATE))
            except (ValueError, TypeError):
                pass
    return _DEFAULT_FX_RATE


async def compute_tax_status(db: SessionFactory, cache: CacheClient) -> None:
    """YTD 실현 PnL로 세금 현황을 계산하여 tax:status 캐시에 기록한다.

    trades 테이블에서 올해 sell 거래의 실현 손익을 합산하고
    22% 세율과 250만원 기본공제를 적용하여 추정 세금을 산출한다.
    """
    year = datetime.now(tz=timezone.utc).year
    fx_rate = await _get_fx_rate(cache)
    gains, losses, _count = await _query_ytd_pnl(db, year)
    net_pnl_usd = gains - losses
    net_pnl_krw = net_pnl_usd * fx_rate
    payload = _build_tax_status_payload(year, gains, losses, net_pnl_usd, net_pnl_krw)
    await cache.write_json("tax:status", payload, ttl=86400)
    estimated = payload["summary"]["estimated_tax_krw"]
    _logger.info("tax:status 기록 완료: net=$%.2f, 추정세금=₩%d", net_pnl_usd, estimated)


def _build_tax_status_payload(
    year: int, gains: float, losses: float,
    net_usd: float, net_krw: float,
) -> dict:
    """tax:status 캐시에 저장할 딕셔너리를 구성한다."""
    taxable_krw = max(net_krw - _ANNUAL_EXEMPTION_KRW, 0.0)
    used_krw = min(max(net_krw, 0.0), _ANNUAL_EXEMPTION_KRW)
    remaining_krw = _ANNUAL_EXEMPTION_KRW - used_krw
    utilization = (used_krw / _ANNUAL_EXEMPTION_KRW * 100.0) if _ANNUAL_EXEMPTION_KRW > 0 else 0.0
    return {
        "year": year,
        "summary": {
            "total_gain_usd": round(gains, 2),
            "total_loss_usd": round(losses, 2),
            "net_gain_usd": round(net_usd, 2),
            "net_gain_krw": round(net_krw, 0),
            "exemption_krw": _ANNUAL_EXEMPTION_KRW,
            "taxable_krw": round(taxable_krw, 0),
            "estimated_tax_krw": round(taxable_krw * _TAX_RATE, 0),
            "tax_rate": _TAX_RATE,
        },
        "remaining_exemption": {
            "exemption_krw": _ANNUAL_EXEMPTION_KRW,
            "used_krw": round(used_krw, 0),
            "remaining_krw": round(remaining_krw, 0),
            "utilization_pct": round(utilization, 1),
        },
    }


async def _query_ytd_pnl(
    db: SessionFactory, year: int,
) -> tuple[float, float, int]:
    """올해 매도 거래에서 총 이익, 총 손실, 거래 수를 반환한다."""
    year_start = f"{year}-01-01"
    sql = text(
        "SELECT ticker, price, quantity, reason, created_at "
        "FROM trades WHERE side = 'sell' AND created_at >= :start "
        "ORDER BY created_at",
    )
    gains = 0.0
    losses = 0.0
    count = 0
    async with db.get_session() as session:
        rows = await session.execute(sql, {"start": year_start})
        for row in rows.fetchall():
            # reason 필드에 pnl 정보가 JSON으로 포함될 수 있다
            pnl = _extract_pnl_from_trade(row)
            if pnl >= 0:
                gains += pnl
            else:
                losses += abs(pnl)
            count += 1
    return gains, losses, count


def _extract_pnl_from_trade(row: object) -> float:
    """거래 행에서 실현 PnL을 추출한다. reason JSON 파싱을 시도한다."""
    reason = getattr(row, "reason", "") or ""
    if reason:
        try:
            data = json.loads(reason)
            if isinstance(data, dict) and "pnl" in data:
                return float(data["pnl"])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return 0.0


async def compute_tax_report(
    db: SessionFactory, cache: CacheClient, year: int,
) -> None:
    """연간 세금 리포트를 계산하여 tax:report:{year} 캐시에 기록한다.

    해당 연도의 모든 매도 거래를 종목별로 집계하고
    단기/장기 보유 구분과 wash sale 건수를 포함한다.
    """
    fx_rate = await _get_fx_rate(cache)
    by_ticker, transactions = await _aggregate_yearly_trades(db, year, fx_rate)

    total_gains = sum(t["gain"] for t in by_ticker.values())
    total_losses = sum(t["loss"] for t in by_ticker.values())
    wash_sales = await _count_wash_sales(db, year)

    payload = {
        "year": year,
        "total_gains": round(total_gains, 2),
        "total_losses": round(total_losses, 2),
        "net_gain": round(total_gains - total_losses, 2),
        "short_term": round(total_gains - total_losses, 2),
        "long_term": 0.0,  # 2x 레버리지 ETF는 단기 보유가 대부분이다
        "wash_sales": wash_sales,
        "transactions": transactions,
    }
    await cache.write_json(f"tax:report:{year}", payload, ttl=86400 * 7)
    _logger.info(
        "tax:report:%d 기록 완료: gain=$%.2f, loss=$%.2f, wash=%d",
        year, total_gains, total_losses, wash_sales,
    )


async def _aggregate_yearly_trades(
    db: SessionFactory, year: int, fx_rate: float,
) -> tuple[dict[str, dict], list[dict]]:
    """해당 연도 매도 거래를 종목별로 집계하고 개별 거래 목록을 반환한다."""
    year_start = f"{year}-01-01"
    year_end = f"{year + 1}-01-01"
    sql = text(
        "SELECT ticker, price, quantity, reason, created_at "
        "FROM trades WHERE side = 'sell' "
        "AND created_at >= :start AND created_at < :end "
        "ORDER BY created_at",
    )
    by_ticker: dict[str, dict] = {}
    transactions: list[dict] = []

    async with db.get_session() as session:
        rows = await session.execute(sql, {"start": year_start, "end": year_end})
        for row in rows.fetchall():
            _accumulate_trade(row, fx_rate, by_ticker, transactions)
    return by_ticker, transactions


def _accumulate_trade(
    row: object, fx_rate: float,
    by_ticker: dict[str, dict], transactions: list[dict],
) -> None:
    """단일 매도 거래를 종목별 집계와 개별 거래 목록에 반영한다."""
    ticker = getattr(row, "ticker", "")
    pnl = _extract_pnl_from_trade(row)
    created = str(getattr(row, "created_at", "") or "")[:10]

    if ticker not in by_ticker:
        by_ticker[ticker] = {"ticker": ticker, "gain": 0.0, "loss": 0.0, "net": 0.0, "trades_count": 0}
    entry = by_ticker[ticker]
    if pnl >= 0:
        entry["gain"] += pnl
    else:
        entry["loss"] += abs(pnl)
    entry["net"] += pnl
    entry["trades_count"] += 1

    tax_krw = max(pnl * fx_rate, 0.0) * _TAX_RATE
    transactions.append({
        "ticker": ticker, "gain_usd": round(pnl, 2),
        "tax_krw": round(tax_krw, 0), "fx_rate": fx_rate, "date": created,
    })


async def _count_wash_sales(db: SessionFactory, year: int) -> int:
    """동일 종목 손실 매도 후 30일 이내 재매수 건수를 반환한다.

    SQLite 전용 datetime() 대신 Python-side 날짜 비교를 사용하여
    PostgreSQL과 SQLite 모두에서 동작하도록 한다.
    """
    year_start = f"{year}-01-01"
    year_end = f"{year + 1}-01-01"

    # 매도 → 매수를 Python에서 매칭하여 DB 이식성을 확보한다
    sell_sql = text(
        "SELECT ticker, created_at FROM trades "
        "WHERE side = 'sell' AND created_at >= :start AND created_at < :end "
        "ORDER BY created_at",
    )
    buy_sql = text(
        "SELECT ticker, created_at FROM trades "
        "WHERE side = 'buy' AND created_at >= :start AND created_at < :end_plus "
        "ORDER BY created_at",
    )
    # 매수 조회 범위: 연말 + 30일까지 (wash sale 판정용)
    buy_end = f"{year + 1}-02-01"  # 넉넉하게 1월 말까지 포함한다

    wash_count = 0
    async with db.get_session() as session:
        sells = (await session.execute(sell_sql, {"start": year_start, "end": year_end})).fetchall()
        buys = (await session.execute(buy_sql, {"start": year_start, "end_plus": buy_end})).fetchall()
        wash_count = _match_wash_sales(sells, buys)
    return wash_count


def _match_wash_sales(
    sells: list, buys: list,
) -> int:
    """매도 후 30일 이내 동일 종목 매수가 있는 건수를 Python에서 판정한다."""
    count = 0
    for sell_row in sells:
        sell_ticker = sell_row.ticker
        sell_dt = sell_row.created_at
        cutoff = sell_dt + timedelta(days=30)
        for buy_row in buys:
            if buy_row.ticker == sell_ticker and sell_dt < buy_row.created_at <= cutoff:
                count += 1
                break
    return count


async def compute_tax_harvest(
    db: SessionFactory, cache: CacheClient,
) -> None:
    """미실현 손실 포지션의 세금 손실 수확 제안을 tax:harvest 캐시에 기록한다.

    현재 포지션 중 미실현 손실이 있는 종목을 식별하고
    wash sale 위험 여부를 30일 이내 동일 종목 매도 이력으로 판단한다.
    """
    fx_rate = await _get_fx_rate(cache)
    positions = await _get_current_positions(cache)

    if not positions:
        await cache.write_json("tax:harvest", [], ttl=86400)
        _logger.info("tax:harvest 기록 완료: 포지션 없음")
        return

    recent_loss_sales = await _get_recent_loss_sales(db)
    candidates = [
        c for pos in positions
        if (c := _build_harvest_candidate(pos, fx_rate, recent_loss_sales)) is not None
    ]
    await cache.write_json("tax:harvest", candidates, ttl=86400)
    total = sum(abs(c["unrealized_loss_usd"]) for c in candidates)
    _logger.info("tax:harvest 기록 완료: %d종목, 총 수확가능=$%.2f", len(candidates), total)


def _build_harvest_candidate(
    pos: dict, fx_rate: float, recent_sales: dict[str, str],
) -> dict | None:
    """단일 포지션의 수확 후보 딕셔너리를 생성한다. 이익 포지션이면 None이다."""
    if pos.get("pnl_pct", 0.0) >= 0:
        return None

    ticker = pos.get("ticker", "")
    avg_price = pos.get("avg_price", 0.0)
    current_price = pos.get("current_price", 0.0)
    quantity = pos.get("quantity", 0)
    loss_usd = (current_price - avg_price) * quantity
    loss_krw = loss_usd * fx_rate

    wash_risk = ticker in recent_sales
    return {
        "ticker": ticker,
        "unrealized_loss_usd": round(loss_usd, 2),
        "unrealized_loss_krw": round(loss_krw, 0),
        "potential_tax_saving_krw": round(abs(loss_krw) * _TAX_RATE, 0),
        "wash_sale_risk": wash_risk,
        "last_loss_sale_date": recent_sales.get(ticker, ""),
        "recommendation": "워시세일 위험" if wash_risk else "매도 추천",
    }


async def _get_current_positions(cache: CacheClient) -> list[dict]:
    """position_monitor가 기록한 WebSocket 캐시에서 현재 포지션을 읽는다."""
    # ws:positions 키에 WebSocket용 포지션 데이터가 기록된다
    data = await cache.read_json("ws:positions")
    if data and isinstance(data, list):
        return data
    # 폴백: pnl:daily에 positions 필드가 있을 수 있다
    pnl = await cache.read_json("pnl:daily")
    if pnl and isinstance(pnl, dict):
        positions = pnl.get("positions", [])
        if isinstance(positions, list):
            return positions
    return []


async def _get_recent_loss_sales(db: SessionFactory) -> dict[str, str]:
    """최근 30일 이내 매도된 종목과 마지막 매도 날짜를 반환한다.

    손실 매도 여부는 reason JSON에서 판별하고, 파싱 실패 시에도
    보수적으로 wash sale 위험으로 간주하여 매도 이력을 포함한다.
    """
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    sql = text(
        "SELECT ticker, reason, created_at "
        "FROM trades WHERE side = 'sell' AND created_at >= :cutoff "
        "ORDER BY created_at DESC",
    )
    result: dict[str, str] = {}
    async with db.get_session() as session:
        rows = await session.execute(sql, {"cutoff": cutoff})
        for row in rows.fetchall():
            ticker = row.ticker
            if ticker in result:
                continue  # 이미 최신 매도 날짜가 기록되어 있다
            pnl = _extract_pnl_from_trade(row)
            # 손실 매도이거나 PnL을 알 수 없으면 보수적으로 포함한다
            if pnl <= 0:
                result[ticker] = str(row.created_at or "")[:10]
    return result

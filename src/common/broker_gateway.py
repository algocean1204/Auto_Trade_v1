"""BrokerGateway (C0.6) -- KIS OpenAPI 인증/주문/시세/잔고 인터페이스이다.

Pydantic 모델 + KisAuth 토큰 관리 + BrokerClient 스텁. 실제 API 호출은 F5에서 구현.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal

import aiohttp
from pydantic import BaseModel

from src.common.error_handler import BrokerError
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_VIRTUAL_BASE: str = "https://openapivts.koreainvestment.com:29443"
_REAL_BASE: str = "https://openapi.koreainvestment.com:9443"
_DATA_DIR: Path = Path(__file__).resolve().parent.parent.parent / "data"
_instance: BrokerClient | None = None


class PriceData(BaseModel):
    """현재가 데이터이다."""
    ticker: str; price: float; change_pct: float; volume: int; timestamp: datetime

class PositionData(BaseModel):
    """보유 포지션이다."""
    ticker: str; quantity: int; avg_price: float; current_price: float; pnl_pct: float

class BalanceData(BaseModel):
    """잔고 데이터이다."""
    total_equity: float; available_cash: float; positions: list[PositionData]

class OrderRequest(BaseModel):
    """주문 요청이다."""
    ticker: str; side: Literal["buy", "sell"]; quantity: int
    order_type: Literal["market", "limit"]; price: float | None = None; exchange: str = "NAS"

class OrderResult(BaseModel):
    """주문 결과이다."""
    order_id: str; status: Literal["filled", "pending", "rejected"]; message: str = ""

class OHLCV(BaseModel):
    """일봉 캔들 데이터이다."""
    date: str; open: float; high: float; low: float; close: float; volume: int


def _token_path(is_real: bool) -> Path:
    """인증 유형에 따른 토큰 캐시 파일 경로를 반환한다."""
    return _DATA_DIR / ("kis_real_token.json" if is_real else "kis_token.json")


_KST = timezone(timedelta(hours=9))


def _load_cached_token(file_path: Path) -> dict | None:
    """캐싱된 토큰을 읽는다. 유효하지 않으면 None을 반환한다."""
    if not file_path.exists():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(data["token_expires_at"])
        # KIS API가 반환하는 만료시간은 KST이다. 타임존 없으면 KST로 처리한다.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=_KST)
        if datetime.now(tz=timezone.utc) < expires:
            return data
        logger.info("토큰 캐시 만료됨: %s (만료: %s)", file_path.name, expires)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("토큰 캐시 파싱 실패: %s", exc)
    return None


def _save_token_cache(file_path: Path, data: dict) -> None:
    """토큰을 파일에 캐싱한다."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


class KisAuth:
    """KIS 인증 토큰 관리자이다. 듀얼 인증(실전+가상) 지원한다."""

    def __init__(self, app_key: str, app_secret: str, account: str, is_real: bool = False) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._account = account
        self._is_real = is_real
        self._base_url = _REAL_BASE if is_real else _VIRTUAL_BASE
        self._token_file = _token_path(is_real)
        self._access_token: str | None = None
        # 캐시된 토큰 복원 시도
        cached = _load_cached_token(self._token_file)
        if cached:
            self._access_token = cached["access_token"]
            logger.info("KIS %s 토큰 캐시 복원", "실전" if is_real else "가상")

    async def get_token(self) -> str:
        """유효한 토큰을 반환한다. 만료 시 자동 갱신한다."""
        if self._access_token is not None:
            return self._access_token
        return await self._issue_token()

    def invalidate_token(self) -> None:
        """만료된 토큰을 무효화하여 다음 get_token() 호출 시 재발급한다."""
        if self._access_token is not None:
            self._access_token = None
            # 캐시 파일도 삭제하여 재시작 시에도 만료 토큰을 사용하지 않도록 한다
            if self._token_file.exists():
                self._token_file.unlink()
            logger.info("KIS %s 토큰 무효화 완료", "실전" if self._is_real else "가상")

    async def _issue_token(self) -> str:
        """POST /oauth2/tokenP로 새 토큰을 발급한다."""
        url = f"{self._base_url}/oauth2/tokenP"
        body = {"grant_type": "client_credentials", "appkey": self._app_key, "appsecret": self._app_secret}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        raise BrokerError(message="KIS 토큰 발급 실패", detail=str(data))
        except aiohttp.ClientError as exc:
            raise BrokerError(message="KIS 토큰 네트워크 오류", detail=str(exc)) from exc
        self._access_token = data["access_token"]
        expires_at = data.get("access_token_token_expired", "")
        _save_token_cache(self._token_file, {
            "account": self._account, "virtual": not self._is_real,
            "access_token": self._access_token, "token_expires_at": expires_at,
        })
        logger.info("KIS %s 토큰 발급 완료", "실전" if self._is_real else "가상")
        return self._access_token  # type: ignore[return-value]

    async def get_headers(self, tr_id: str) -> dict[str, str]:
        """API 호출용 공통 헤더를 생성한다."""
        token = await self.get_token()
        return {
            "authorization": f"Bearer {token}", "appkey": self._app_key,
            "appsecret": self._app_secret, "tr_id": tr_id,
            "Content-Type": "application/json; charset=utf-8",
        }


class BrokerClient:
    """KIS 브로커 통합 클라이언트이다. 메서드 구현은 F5에서 완성한다."""

    def __init__(self, virtual_auth: KisAuth, real_auth: KisAuth) -> None:
        self.virtual_auth = virtual_auth
        self.real_auth = real_auth
        logger.info("BrokerClient 초기화 완료 (듀얼 인증)")

    async def get_price(self, ticker: str, exchange: str = "NAS") -> PriceData:
        raise NotImplementedError("F5에서 구현 예정")

    async def get_balance(self) -> BalanceData:
        raise NotImplementedError("F5에서 구현 예정")

    async def place_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError("F5에서 구현 예정")

    async def get_exchange_rate(self) -> float:
        raise NotImplementedError("F5에서 구현 예정")

    async def get_daily_candles(self, ticker: str, days: int = 30, exchange: str = "NAS") -> list[OHLCV]:
        raise NotImplementedError("F5에서 구현 예정")

    async def close(self) -> None:
        logger.info("BrokerClient 종료 완료")


def get_broker_client(
    app_key: str | None = None, app_secret: str | None = None,
    virtual_account: str | None = None, real_app_key: str | None = None,
    real_app_secret: str | None = None, real_account: str | None = None,
) -> BrokerClient:
    """BrokerClient 싱글톤을 반환한다. 최초 호출 시 KIS 시크릿 6개 필수이다.

    BrokerClientImpl(F5.2)을 생성하여 실제 KIS API 호출이 가능한 인스턴스를 반환한다.
    """
    global _instance
    if _instance is not None:
        return _instance
    params = {"app_key": app_key, "app_secret": app_secret, "virtual_account": virtual_account,
              "real_app_key": real_app_key, "real_app_secret": real_app_secret, "real_account": real_account}
    missing = [k for k, v in params.items() if not v]
    if missing:
        raise ValueError(f"최초 호출 시 KIS 시크릿 필수. 누락: {', '.join(missing)}")
    # F5.2: BrokerClientImpl로 실제 KIS API 연결
    from src.common.http_client import get_http_client
    from src.executor.broker.client_impl import BrokerClientImpl
    virtual_auth = KisAuth(app_key=app_key, app_secret=app_secret, account=virtual_account, is_real=False)  # type: ignore[arg-type]
    real_auth = KisAuth(app_key=real_app_key, app_secret=real_app_secret, account=real_account, is_real=True)  # type: ignore[arg-type]
    http = get_http_client()
    _instance = BrokerClientImpl(virtual_auth=virtual_auth, real_auth=real_auth, http=http)
    return _instance


def reset_broker_client() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None

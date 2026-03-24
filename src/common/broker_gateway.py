"""BrokerGateway (C0.6) -- KIS OpenAPI 인증/주문/시세/잔고 인터페이스이다.

Pydantic 모델 + KisAuth 토큰 관리 + BrokerClient 스텁. 실제 API 호출은 F5에서 구현.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import aiohttp
from pydantic import BaseModel

from src.common.error_handler import BrokerError
from src.common.logger import get_logger
from src.common.paths import get_data_dir

logger: logging.Logger = get_logger(__name__)

# KIS OpenAPI 베이스 URL — 다른 모듈에서도 참조하므로 공개 상수로 정의한다
KIS_VIRTUAL_BASE: str = "https://openapivts.koreainvestment.com:29443"
KIS_REAL_BASE: str = "https://openapi.koreainvestment.com:9443"
_instance: BrokerClient | None = None


class PriceData(BaseModel):
    """현재가 데이터이다."""
    ticker: str; price: float; change_pct: float; volume: int; timestamp: datetime
    avg_volume: int = 0  # 250일 평균 거래량 (KIS d250_vavg_clam)

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
    return get_data_dir() / ("kis_real_token.json" if is_real else "kis_token.json")


# KIS API 토큰 만료 시각이 KST이므로 ZoneInfo를 사용하여 일관성을 유지한다
_KST = ZoneInfo("Asia/Seoul")


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
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, OSError) as exc:
        logger.warning("토큰 캐시 파싱 실패: %s", exc)
    return None


def _save_token_cache(file_path: Path, data: dict) -> None:
    """토큰을 파일에 원자적으로 캐싱한다. 소유자만 읽기/쓰기 가능하도록 권한을 설정한다.

    임시 파일에 먼저 기록한 뒤 os.replace로 교체하여
    crash 시 깨진 JSON과 권한 설정 전 파일 노출을 방지한다.
    """
    import os
    import tempfile

    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    fd, tmp = tempfile.mkstemp(
        dir=str(file_path.parent), suffix=".tmp", prefix=".token_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(file_path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class KisAuth:
    """KIS 인증 토큰 관리자이다. 듀얼 인증(실전+가상) 지원한다."""

    # 만료 10분 전에 선제 갱신한다
    _REFRESH_MARGIN = timedelta(minutes=10)

    def __init__(self, app_key: str, app_secret: str, account: str, is_real: bool = False) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._account = account
        self._is_real = is_real
        self._base_url = KIS_REAL_BASE if is_real else KIS_VIRTUAL_BASE
        self._token_file = _token_path(is_real)
        self._access_token: str | None = None
        self._expires_at: datetime | None = None
        # 토큰 발급 경합 방지 Lock — 동시 get_token() 호출 시 중복 발급을 막는다
        self._token_lock: asyncio.Lock | None = None
        # 캐시된 토큰 복원 시도
        cached = _load_cached_token(self._token_file)
        if cached and cached.get("access_token"):
            self._access_token = cached["access_token"]
            try:
                exp = datetime.fromisoformat(cached["token_expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=_KST)
                self._expires_at = exp
            except (KeyError, ValueError):
                pass
            logger.info("KIS %s 토큰 캐시 복원 (만료: %s)", "실전" if is_real else "가상", self._expires_at)

    @property
    def base_url(self) -> str:
        """인증 유형에 맞는 KIS API 기본 URL을 반환한다."""
        return self._base_url

    @property
    def account(self) -> str:
        """계좌번호를 반환한다."""
        return self._account

    @property
    def is_real(self) -> bool:
        """실전 투자 여부를 반환한다."""
        return self._is_real

    def _is_token_valid(self) -> bool:
        """메모리 토큰이 유효한지 확인한다. 만료 마진을 적용한다."""
        if not self._access_token or self._expires_at is None:
            return False
        return datetime.now(tz=timezone.utc) < (self._expires_at - self._REFRESH_MARGIN)

    def _get_token_lock(self) -> asyncio.Lock:
        """토큰 Lock을 lazy 초기화한다.

        __init__에서 이벤트 루프가 없을 수 있으므로 최초 사용 시 생성한다.
        """
        if self._token_lock is None:
            self._token_lock = asyncio.Lock()
        return self._token_lock

    async def get_token(self) -> str:
        """유효한 토큰을 반환한다. 만료(또는 만료 임박) 시 자동 갱신한다.

        Lock으로 동시 호출 시 중복 토큰 발급을 방지한다.
        첫 번째 호출이 발급을 완료하면 나머지 호출은 유효한 토큰을 반환한다.
        """
        if self._is_token_valid():
            return self._access_token  # type: ignore[return-value]
        async with self._get_token_lock():
            # Lock 획득 후 재검사 — 다른 코루틴이 이미 갱신했을 수 있다
            if self._is_token_valid():
                return self._access_token  # type: ignore[return-value]
            if self._access_token is not None:
                logger.info("KIS %s 토큰 만료/임박 → 자동 갱신", "실전" if self._is_real else "가상")
            return await self._issue_token()

    async def force_refresh(self) -> str:
        """기존 토큰을 무시하고 강제로 새 토큰을 발급한다.

        Lock을 획득하여 get_token()과의 동시 호출 시 중복 발급을 방지한다.
        """
        async with self._get_token_lock():
            logger.info("KIS %s 토큰 강제 재발급 시작", "실전" if self._is_real else "가상")
            self._access_token = None
            self._expires_at = None
            return await self._issue_token()

    def invalidate_token(self) -> None:
        """만료된 토큰을 무효화하여 다음 get_token() 호출 시 재발급한다."""
        if self._access_token is not None:
            self._access_token = None
            self._expires_at = None
            # 캐시 파일도 삭제하여 재시작 시에도 만료 토큰을 사용하지 않도록 한다
            if self._token_file.exists():
                self._token_file.unlink()
            logger.info("KIS %s 토큰 무효화 완료", "실전" if self._is_real else "가상")

    async def _issue_token(self) -> str:
        """POST /oauth2/tokenP로 새 토큰을 발급한다."""
        url = f"{self._base_url}/oauth2/tokenP"
        body = {"grant_type": "client_credentials", "appkey": self._app_key, "appsecret": self._app_secret}
        # 토큰 발급 요청에 30초 타임아웃을 적용하여 서버 무응답 시 무한 대기를 방지한다
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        raise BrokerError(message="KIS 토큰 발급 실패", detail=str(data))
        except aiohttp.ClientError as exc:
            raise BrokerError(message="KIS 토큰 네트워크 오류", detail=str(exc)) from exc
        token = data.get("access_token")
        if not token:
            raise BrokerError(
                message="KIS 토큰 응답에 access_token 필드 부재",
                detail=str(data)[:500],
            )
        self._access_token = token
        expires_str: str = data.get("access_token_token_expired", "")
        # 만료 시간을 메모리에 저장하여 선제 갱신에 사용한다
        try:
            exp = datetime.fromisoformat(expires_str)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_KST)
            self._expires_at = exp
        except (ValueError, TypeError):
            # 만료시간 파싱 실패 시 기본 24시간으로 설정하여 무한 재발급 루프를 방지한다
            self._expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=24)
            logger.warning("토큰 만료시간 파싱 실패 ('%s') → 기본 24시간 설정", expires_str)
        # 캐시 저장 실패는 토큰 발급 자체를 중단시키지 않는다 — 메모리 토큰만으로 운영 가능하다
        try:
            _save_token_cache(self._token_file, {
                "account": self._account, "virtual": not self._is_real,
                "access_token": self._access_token, "token_expires_at": expires_str,
            })
        except OSError as exc:
            logger.warning("토큰 캐시 저장 실패 (메모리 토큰만 사용): %s", exc)
        logger.info("KIS %s 토큰 발급 완료 (만료: %s)", "실전" if self._is_real else "가상", self._expires_at)
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

    def __init__(self, virtual_auth: KisAuth | None, real_auth: KisAuth | None) -> None:
        self.virtual_auth = virtual_auth
        self.real_auth = real_auth
        modes = []
        if virtual_auth:
            modes.append("가상")
        if real_auth:
            modes.append("실전")
        logger.info("BrokerClient 초기화 완료 (인증: %s)", "+".join(modes) or "없음")

    async def get_price(self, ticker: str, exchange: str = "NAS") -> PriceData:
        raise NotImplementedError("F5에서 구현 예정")

    async def get_balance(self) -> BalanceData:
        raise NotImplementedError("F5에서 구현 예정")

    async def place_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError("F5에서 구현 예정")

    async def cancel_order(self, order_id: str, exchange: str = "NAS") -> object:
        """미체결 주문을 취소한다. CancelResult를 반환한다.

        반환 타입을 object로 선언하여 순환 임포트를 방지한다.
        실제 반환값은 kis_api.CancelResult이다.
        """
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
    """BrokerClient 싱글톤을 반환한다. 최소 1개 KIS 키 쌍(가상 또는 실전)이 필요하다.

    가상/실전 중 하나만 설정해도 초기화 가능하다.
    누락된 쪽은 KisAuth를 생성하지 않고 None으로 전달한다.
    """
    global _instance
    if _instance is not None:
        return _instance
    has_virtual = all([app_key, app_secret, virtual_account])
    has_real = all([real_app_key, real_app_secret, real_account])
    if not has_virtual and not has_real:
        raise ValueError(
            "최소 1개 KIS 키 쌍(가상 또는 실전)이 필요하다. "
            "가상: app_key, app_secret, virtual_account / "
            "실전: real_app_key, real_app_secret, real_account"
        )
    # F5.2: BrokerClientImpl로 실제 KIS API 연결
    from src.common.http_client import get_http_client
    from src.executor.broker.client_impl import BrokerClientImpl
    virtual_auth: KisAuth | None = None
    real_auth: KisAuth | None = None
    if has_virtual:
        virtual_auth = KisAuth(app_key=app_key, app_secret=app_secret, account=virtual_account, is_real=False)  # type: ignore[arg-type]
    if has_real:
        real_auth = KisAuth(app_key=real_app_key, app_secret=real_app_secret, account=real_account, is_real=True)  # type: ignore[arg-type]
    http = get_http_client()
    _instance = BrokerClientImpl(virtual_auth=virtual_auth, real_auth=real_auth, http=http)
    return _instance


def reset_broker_client() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None

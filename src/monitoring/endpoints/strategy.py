"""F7.23 StrategyEndpoints -- 전략 파라미터 조회/수정 API이다.

strategy_params.json 전체 읽기 및 부분 업데이트를 제공한다.
업데이트 전 백업 파일을 생성하여 데이터 손실을 방지한다.
Flutter 대시보드에서 /api/strategy/params 경로로 호출한다.

티커별 파라미터 오버라이드 관리:
  - GET  /api/strategy/ticker-params        : 전체 오버라이드 조회
  - GET  /api/strategy/ticker-params/{ticker}: 특정 티커 오버라이드 조회
  - PUT  /api/strategy/ticker-params/{ticker}: 티커 오버라이드 설정 (인증 필수)
  - DELETE /api/strategy/ticker-params/{ticker}: 티커 오버라이드 삭제 (인증 필수)
  - POST /api/strategy/ticker-params/ai-optimize: AI 최적화 트리거 (인증 필수)

오버라이드는 strategy_params.json 의 ticker_params 키 아래에 저장된다.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# ApiConstants.strategyParams = '/api/strategy/params' 와 일치하는 접두어를 사용한다
strategy_router = APIRouter(prefix="/api/strategy", tags=["strategy"])

_system: InjectedSystem | None = None

# strategy_params.json 절대 경로 (프로젝트 루트 기준)
_PARAMS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "strategy_params.json"


class StrategyParamsResponse(BaseModel):
    """전략 파라미터 조회 응답 모델이다."""

    params: dict[str, Any] = Field(default_factory=dict)
    path: str = ""


class StrategyParamsUpdateResponse(BaseModel):
    """전략 파라미터 업데이트 응답 모델이다."""

    status: str
    updated_keys: list[str] = Field(default_factory=list)
    backup: str | None = None


def set_strategy_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("StrategyEndpoints 의존성 주입 완료")


def _load_params_raw() -> dict[str, Any]:
    """strategy_params.json을 raw dict로 로드한다. 없으면 빈 dict를 반환한다."""
    if not _PARAMS_PATH.exists():
        _logger.warning("strategy_params.json 없음: %s", _PARAMS_PATH)
        return {}
    try:
        text = _PARAMS_PATH.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        _logger.exception("strategy_params.json 로드 실패")
        return {}


def _backup_params() -> str | None:
    """strategy_params.json을 타임스탬프 백업 파일로 복사한다.

    백업 파일명 형식: strategy_params_{YYYYMMDD_HHMMSS}.json
    백업 성공 시 파일명 반환, 실패 시 None 반환.
    """
    if not _PARAMS_PATH.exists():
        return None
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"strategy_params_{ts}.json"
        backup_path = _PARAMS_PATH.parent / backup_name
        shutil.copy2(_PARAMS_PATH, backup_path)
        _logger.info("전략 파라미터 백업 생성: %s", backup_name)
        return backup_name
    except Exception:
        _logger.exception("전략 파라미터 백업 실패")
        return None


def _write_params(data: dict[str, Any]) -> None:
    """dict를 strategy_params.json에 기록한다."""
    _PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PARAMS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


@strategy_router.get("/params", response_model=StrategyParamsResponse)
async def get_strategy_params() -> StrategyParamsResponse:
    """전략 파라미터 전체를 반환한다.

    Flutter StrategyParams.fromJson이 raw dict를 파싱하므로
    파일 내용을 그대로 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        params = _load_params_raw()
        return StrategyParamsResponse(params=params, path=str(_PARAMS_PATH))
    except Exception:
        _logger.exception("전략 파라미터 조회 실패")
        raise HTTPException(status_code=500, detail="파라미터 조회 실패") from None


@strategy_router.put("/params", response_model=StrategyParamsUpdateResponse)
async def update_strategy_params(
    body: dict[str, Any],
    _key: str = Depends(verify_api_key),
) -> StrategyParamsUpdateResponse:
    """전략 파라미터를 부분 업데이트한다. 인증 필수.

    Flutter는 PUT 메서드로 {"params": {...}} 형태를 전송한다.
    업데이트 전 백업을 생성하고, 기존 파라미터에 병합한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        # Flutter 전송 형식 처리: {"params": {...}} 또는 flat dict
        updates: dict[str, Any] = body.get("params", body)
        if not isinstance(updates, dict):
            raise HTTPException(
                status_code=422,
                detail="params 필드는 dict여야 한다",
            )

        # 기존 파라미터 로드 후 병합
        existing = _load_params_raw()
        merged = {**existing, **updates}

        # 업데이트 전 백업
        backup_name = _backup_params()

        # 저장
        _write_params(merged)
        _logger.info("전략 파라미터 업데이트 완료: %d개 항목 변경", len(updates))

        return StrategyParamsUpdateResponse(
            status="updated",
            updated_keys=list(updates.keys()),
            backup=backup_name,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("전략 파라미터 업데이트 실패")
        raise HTTPException(status_code=500, detail="파라미터 업데이트 실패") from None


# ── 티커별 파라미터 오버라이드 -- 응답 모델 ────────────────────────────────

# strategy_params.json 안의 ticker_params 섹션 키 이름이다
_TICKER_PARAMS_KEY = "ticker_params"


class TickerParamsAllResponse(BaseModel):
    """전체 티커 오버라이드 조회 응답 모델이다."""

    ticker_params: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TickerParamsSingleResponse(BaseModel):
    """단일 티커 오버라이드 조회 응답 모델이다."""

    ticker: str
    params: dict[str, Any] = Field(default_factory=dict)


class TickerParamsUpdateRequest(BaseModel):
    """티커 오버라이드 설정 요청 모델이다."""

    param_name: str = Field(..., description="오버라이드할 파라미터 이름")
    value: Any = Field(..., description="파라미터 값 (숫자, 불리언 모두 허용)")


class TickerParamsUpdateResponse(BaseModel):
    """티커 오버라이드 설정 응답 모델이다."""

    status: str
    ticker: str
    param_name: str
    value: Any


class TickerParamsDeleteResponse(BaseModel):
    """티커 오버라이드 삭제 응답 모델이다."""

    status: str
    ticker: str
    cleared_params: list[str] = Field(default_factory=list)


class AiOptimizeResponse(BaseModel):
    """AI 최적화 트리거 응답 모델이다."""

    status: str
    message: str


# ── 내부 헬퍼: ticker_params 섹션 읽기/쓰기 ───────────────────────────────

def _load_ticker_params() -> dict[str, dict[str, Any]]:
    """strategy_params.json 에서 ticker_params 섹션을 로드한다.

    섹션이 없으면 빈 dict를 반환한다.
    """
    raw = _load_params_raw()
    section = raw.get(_TICKER_PARAMS_KEY, {})
    # 타입 안전성 보장: 값이 dict가 아닌 경우 무시한다
    if not isinstance(section, dict):
        _logger.warning("ticker_params 섹션 형식 오류 — 빈 dict로 초기화한다")
        return {}
    return {k: v for k, v in section.items() if isinstance(v, dict)}


def _save_ticker_params(ticker_params: dict[str, dict[str, Any]]) -> str | None:
    """ticker_params 섹션을 strategy_params.json 에 저장한다.

    전체 파라미터 파일을 읽고 ticker_params 키만 교체하여 저장한다.
    저장 전 백업 파일을 생성하고 백업 파일명을 반환한다.
    """
    existing = _load_params_raw()
    existing[_TICKER_PARAMS_KEY] = ticker_params
    backup_name = _backup_params()
    _write_params(existing)
    return backup_name


# ── 티커별 파라미터 오버라이드 -- 엔드포인트 ─────────────────────────────

@strategy_router.get("/ticker-params", response_model=TickerParamsAllResponse)
async def get_all_ticker_params() -> TickerParamsAllResponse:
    """모든 티커별 파라미터 오버라이드를 반환한다.

    strategy_params.json 의 ticker_params 섹션 전체를 반환한다.
    오버라이드가 없으면 빈 dict를 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        ticker_params = _load_ticker_params()
        return TickerParamsAllResponse(ticker_params=ticker_params)
    except Exception:
        _logger.exception("전체 티커 파라미터 조회 실패")
        raise HTTPException(status_code=500, detail="티커 파라미터 조회 실패") from None


@strategy_router.get("/ticker-params/{ticker}", response_model=TickerParamsSingleResponse)
async def get_ticker_params(ticker: str) -> TickerParamsSingleResponse:
    """특정 티커의 파라미터 오버라이드를 반환한다.

    해당 티커에 오버라이드가 없으면 404를 반환한다.
    ticker는 대문자로 정규화한다 (예: soxl → SOXL).
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        normalized = ticker.upper()
        ticker_params = _load_ticker_params()
        if normalized not in ticker_params:
            raise HTTPException(
                status_code=404,
                detail=f"티커 오버라이드 없음: {normalized}",
            )
        return TickerParamsSingleResponse(ticker=normalized, params=ticker_params[normalized])
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 파라미터 조회 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="티커 파라미터 조회 실패") from None


@strategy_router.put(
    "/ticker-params/{ticker}",
    response_model=TickerParamsUpdateResponse,
)
async def set_ticker_param(
    ticker: str,
    body: TickerParamsUpdateRequest,
    _key: str = Depends(verify_api_key),
) -> TickerParamsUpdateResponse:
    """특정 티커의 파라미터 오버라이드를 설정한다. 인증 필수.

    ticker_params.{ticker}.{param_name} = value 형태로 저장한다.
    이미 해당 티커 오버라이드가 있으면 해당 파라미터만 덮어쓴다.
    없으면 새 티커 섹션을 생성한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        normalized = ticker.upper()
        ticker_params = _load_ticker_params()

        # 티커 섹션이 없으면 새로 생성한다
        if normalized not in ticker_params:
            ticker_params[normalized] = {}

        # 단일 파라미터를 설정한다
        ticker_params[normalized][body.param_name] = body.value
        _save_ticker_params(ticker_params)

        _logger.info(
            "티커 파라미터 오버라이드 설정: %s.%s = %s",
            normalized,
            body.param_name,
            body.value,
        )
        return TickerParamsUpdateResponse(
            status="updated",
            ticker=normalized,
            param_name=body.param_name,
            value=body.value,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 파라미터 설정 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="티커 파라미터 설정 실패") from None


@strategy_router.delete(
    "/ticker-params/{ticker}",
    response_model=TickerParamsDeleteResponse,
)
async def delete_ticker_params(
    ticker: str,
    _key: str = Depends(verify_api_key),
) -> TickerParamsDeleteResponse:
    """특정 티커의 모든 파라미터 오버라이드를 삭제한다. 인증 필수.

    해당 티커 섹션 전체를 ticker_params 에서 제거한다.
    오버라이드가 없는 티커를 삭제 시도하면 404를 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        normalized = ticker.upper()
        ticker_params = _load_ticker_params()

        if normalized not in ticker_params:
            raise HTTPException(
                status_code=404,
                detail=f"삭제할 티커 오버라이드 없음: {normalized}",
            )

        # 삭제 전 파라미터 이름 목록을 기록한다
        cleared_keys = list(ticker_params[normalized].keys())
        del ticker_params[normalized]
        _save_ticker_params(ticker_params)

        _logger.info("티커 파라미터 오버라이드 삭제: %s (%d개)", normalized, len(cleared_keys))
        return TickerParamsDeleteResponse(
            status="deleted",
            ticker=normalized,
            cleared_params=cleared_keys,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("티커 파라미터 삭제 실패: %s", ticker)
        raise HTTPException(status_code=500, detail="티커 파라미터 삭제 실패") from None


# ── AI 최적화 트리거 ─────────────────────────────────────────────────────

# 동시 실행 방지 락 — 중복 호출 시 두 번째 최적화가 params.json을 덮어쓰는 것을 방지한다
_optimize_lock = asyncio.Lock()


async def _run_ai_optimize_task() -> None:
    """AI 파라미터 최적화를 백그라운드에서 실행한다.

    execution_optimizer 피처가 등록되어 있으면 EOD 최적화 로직을 호출한다.
    없으면 경고 로그만 남기고 종료한다.
    """
    if _system is None:
        _logger.warning("AI 최적화 실행 중 시스템이 None이다 — 스킵")
        return
    async with _optimize_lock:
        try:
            optimizer = _system.features.get("execution_optimizer")  # type: ignore[union-attr]
            if optimizer is None:
                _logger.warning("execution_optimizer 피처가 등록되지 않았다 — AI 최적화 스킵")
                return
            # 최적화 모듈의 run() 메서드를 호출한다 (ParamTuner 규약)
            await optimizer.run()
            _logger.info("AI 파라미터 최적화 완료")
        except Exception:
            _logger.exception("AI 파라미터 최적화 실패")


@strategy_router.post("/ticker-params/ai-optimize", response_model=AiOptimizeResponse)
async def trigger_ai_optimize(
    _key: str = Depends(verify_api_key),
) -> AiOptimizeResponse:
    """AI 기반 파라미터 최적화를 트리거한다. 인증 필수.

    백그라운드 asyncio 태스크로 즉시 반환하고 비동기로 실행한다.
    execution_optimizer 피처를 통해 EOD 분석 결과를 반영한 파라미터 조정을 수행한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    if _optimize_lock.locked():
        return AiOptimizeResponse(
            status="already_running",
            message="AI 파라미터 최적화가 이미 실행 중이다.",
        )
    try:
        # 즉시 반환 후 백그라운드 실행한다
        asyncio.create_task(_run_ai_optimize_task())
        _logger.info("AI 파라미터 최적화 태스크 시작")
        return AiOptimizeResponse(
            status="triggered",
            message="AI 파라미터 최적화가 백그라운드에서 시작되었다. 완료까지 수십 초가 소요된다.",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("AI 최적화 트리거 실패")
        raise HTTPException(status_code=500, detail="AI 최적화 트리거 실패") from None

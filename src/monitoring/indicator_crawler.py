"""
주요 매크로 지표 자동 크롤러.

1시간마다 VIX, Fear&Greed, CPI, Fed Rate, 국채 스프레드, 10Y/2Y 국채 수익률,
실업률 등을 병렬로 조회하고 DB에 저장한다.
네트워크 연결 확인 후 크롤링을 수행하며, Claude Sonnet 분석이 있으면
지표 변화에 대한 시장 해석을 생성한다.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from src.db.connection import get_session
from src.db.models import IndicatorHistory
from src.monitoring.fred_client import (
    calc_fear_greed,
    fetch_cnn_fear_greed,
    fetch_fred_latest,
    fetch_vix_value,
    treasury_spread_signal,
    vix_level,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 레짐 판단 임계값 상수
_REGIME_VIX_HIGH = 25.0
_REGIME_VIX_EXTREME = 35.0
_REGIME_SPREAD_INVERTED = -0.3
_REGIME_SPREAD_FLAT = 0.0

# Sonnet 분석 트리거 임계값 (변화량)
_CHANGE_THRESHOLD_VIX = 1.5
_CHANGE_THRESHOLD_SPREAD = 0.1
_CHANGE_THRESHOLD_FED = 0.01
_CHANGE_THRESHOLD_FEAR_GREED = 5

# 네트워크 연결 확인용 HTTP 요청 타임아웃 (초)
_NETWORK_CHECK_TIMEOUT: float = 5.0


class IndicatorCrawler:
    """주요 매크로 지표를 1시간마다 자동 크롤링하고 DB에 저장하는 서비스이다."""

    def __init__(self, claude_client: Any = None) -> None:
        """IndicatorCrawler를 초기화한다.

        Args:
            claude_client: ClaudeClient 인스턴스. None이면 Sonnet 분석을 건너뛴다.
        """
        self._task: asyncio.Task[None] | None = None
        self._claude_client = claude_client
        self._interval: int = 3600  # 1시간(초)
        self._last_results: dict[str, Any] = {}
        self._last_update: datetime | None = None
        self._last_analysis: str | None = None
        self._running: bool = False

    async def start(self) -> None:
        """백그라운드 주기 크롤링을 시작한다.

        이미 실행 중이면 아무 작업도 수행하지 않는다.
        """
        if self._running:
            logger.debug("IndicatorCrawler 이미 실행 중 - 중복 시작 무시")
            return

        self._running = True
        self._task = asyncio.create_task(self._crawl_loop(), name="indicator_crawler")
        logger.info("IndicatorCrawler 시작 (1시간 주기)")

    async def stop(self) -> None:
        """백그라운드 크롤링을 중지한다."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("IndicatorCrawler 중지 완료")

    async def _crawl_loop(self) -> None:
        """메인 루프: 시작 즉시 1회 실행 후 1시간 간격으로 반복한다."""
        logger.info("IndicatorCrawler 루프 시작")
        while self._running:
            try:
                await self.crawl_once()
            except Exception as exc:
                logger.error("IndicatorCrawler 크롤링 루프 예외: %s", exc, exc_info=True)

            # 1시간 대기 (취소 가능)
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                logger.info("IndicatorCrawler 루프 취소됨")
                break

    async def crawl_once(self) -> dict[str, Any]:
        """모든 지표를 1회 크롤링한다.

        네트워크 연결을 확인한 뒤 모든 지표를 병렬로 조회하고 DB에 저장한다.
        Sonnet 분석이 구성되어 있으면 분석도 수행한다.

        Returns:
            조회된 지표 딕셔너리. 네트워크 불가 시 빈 딕셔너리를 반환한다.
        """
        logger.info("IndicatorCrawler 1회 크롤링 시작")

        if not await self._check_network():
            logger.warning("네트워크 연결 없음 - 크롤링 건너뜀")
            return {}

        try:
            indicators = await self._fetch_all_indicators()
        except Exception as exc:
            logger.error("지표 일괄 조회 실패: %s", exc, exc_info=True)
            return {}

        if not indicators:
            logger.warning("조회된 지표 없음")
            return {}

        # 레짐 계산 추가
        indicators["regime"] = self._calc_regime(indicators)

        # DB 저장
        try:
            await self._save_to_db(indicators)
        except Exception as exc:
            logger.error("지표 DB 저장 실패: %s", exc, exc_info=True)

        # Sonnet 분석 (오류가 발생해도 크롤링 결과에는 영향 없음)
        try:
            analysis = await self._analyze_with_sonnet(indicators)
            if analysis:
                self._last_analysis = analysis
        except Exception as exc:
            logger.warning("Sonnet 분석 실패 (무시): %s", exc)

        # 인메모리 캐시 갱신
        self._last_results = indicators
        self._last_update = datetime.now(timezone.utc)

        logger.info(
            "IndicatorCrawler 1회 크롤링 완료 (지표수=%d)", len(indicators)
        )
        return indicators

    async def _check_network(self) -> bool:
        """네트워크 연결 상태를 확인한다.

        google.com으로 HTTP GET 요청을 전송하여 연결 가능 여부를 검사한다.
        5초 타임아웃을 적용한다.

        Returns:
            연결 가능하면 True, 그렇지 않으면 False.
        """
        try:
            async with httpx.AsyncClient(timeout=_NETWORK_CHECK_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get("https://www.google.com")
                return resp.status_code < 500
        except Exception as exc:
            logger.debug("네트워크 연결 확인 실패: %s", exc)
            return False

    async def _fetch_all_indicators(self) -> dict[str, Any]:
        """모든 지표를 병렬로 조회한다.

        FRED API, CNN Fear&Greed API를 병렬로 호출하여 지표를 수집한다.
        개별 지표 조회 실패 시 해당 지표는 None으로 처리하고 나머지는 정상 반환한다.

        Returns:
            지표명을 키, 조회 결과를 값으로 하는 딕셔너리.
        """
        api_key = os.getenv("FRED_API_KEY", "")

        task_defs: dict[str, Any] = {
            "vix_raw": fetch_vix_value(),
            "fear_greed_raw": fetch_cnn_fear_greed(),
            "fed_rate_raw": fetch_fred_latest("DFF", api_key) if api_key else _noop(),
            "cpi_raw": fetch_fred_latest("CPIAUCSL", api_key) if api_key else _noop(),
            "spread_10y2y_raw": fetch_fred_latest("T10Y2Y", api_key) if api_key else _noop(),
            "yield_10y_raw": fetch_fred_latest("DGS10", api_key) if api_key else _noop(),
            "yield_2y_raw": fetch_fred_latest("DGS2", api_key) if api_key else _noop(),
            "unemployment_raw": fetch_fred_latest("UNRATE", api_key) if api_key else _noop(),
        }

        keys = list(task_defs.keys())
        coroutines = list(task_defs.values())

        gathered: list[Any] = list(
            await asyncio.gather(*coroutines, return_exceptions=True)
        )

        raw: dict[str, Any] = {}
        for key, result in zip(keys, gathered):
            if isinstance(result, Exception):
                logger.warning("지표 조회 실패 (%s): %s", key, result)
                raw[key] = None
            else:
                raw[key] = result

        # 조회 결과를 정규화된 지표 딕셔너리로 변환한다.
        indicators: dict[str, Any] = {}

        # VIX
        vix_val = raw.get("vix_raw")
        if isinstance(vix_val, (int, float)):
            indicators["vix"] = {
                "value": round(float(vix_val), 2),
                "level": vix_level(float(vix_val)),
            }
        else:
            indicators["vix"] = None

        # Fear & Greed
        fg = raw.get("fear_greed_raw")
        if isinstance(fg, dict):
            indicators["fear_greed"] = fg
        else:
            # VIX 기반 폴백
            if indicators.get("vix") and indicators["vix"] is not None:
                vix_v = indicators["vix"]["value"]
                indicators["fear_greed"] = calc_fear_greed(vix_v)
            else:
                indicators["fear_greed"] = None

        # Fed Rate
        fed_raw = raw.get("fed_rate_raw")
        if isinstance(fed_raw, dict) and fed_raw.get("current_value") is not None:
            indicators["fed_rate"] = {
                "value": float(fed_raw["current_value"]),
                "date": fed_raw.get("current_date"),
                "previous": fed_raw.get("previous_value"),
            }
        else:
            indicators["fed_rate"] = None

        # CPI
        cpi_raw = raw.get("cpi_raw")
        if isinstance(cpi_raw, dict) and cpi_raw.get("current_value") is not None:
            cv = float(cpi_raw["current_value"])
            pv = cpi_raw.get("previous_value")
            indicators["cpi"] = {
                "value": cv,
                "date": cpi_raw.get("current_date"),
                "previous": float(pv) if pv is not None else None,
                "change": round(cv - float(pv), 2) if pv is not None else None,
            }
        else:
            indicators["cpi"] = None

        # 10Y-2Y Spread
        spread_raw = raw.get("spread_10y2y_raw")
        if isinstance(spread_raw, dict) and spread_raw.get("current_value") is not None:
            sv = float(spread_raw["current_value"])
            indicators["spread_10y2y"] = {
                "value": round(sv, 3),
                "signal": treasury_spread_signal(sv),
                "date": spread_raw.get("current_date"),
            }
        else:
            indicators["spread_10y2y"] = None

        # 10Y Yield
        y10_raw = raw.get("yield_10y_raw")
        if isinstance(y10_raw, dict) and y10_raw.get("current_value") is not None:
            indicators["yield_10y"] = {
                "value": round(float(y10_raw["current_value"]), 3),
                "date": y10_raw.get("current_date"),
            }
        else:
            indicators["yield_10y"] = None

        # 2Y Yield
        y2_raw = raw.get("yield_2y_raw")
        if isinstance(y2_raw, dict) and y2_raw.get("current_value") is not None:
            indicators["yield_2y"] = {
                "value": round(float(y2_raw["current_value"]), 3),
                "date": y2_raw.get("current_date"),
            }
        else:
            indicators["yield_2y"] = None

        # Unemployment
        unrate_raw = raw.get("unemployment_raw")
        if isinstance(unrate_raw, dict) and unrate_raw.get("current_value") is not None:
            uv = float(unrate_raw["current_value"])
            pv = unrate_raw.get("previous_value")
            indicators["unemployment"] = {
                "value": uv,
                "date": unrate_raw.get("current_date"),
                "previous": float(pv) if pv is not None else None,
                "change": round(uv - float(pv), 2) if pv is not None else None,
            }
        else:
            indicators["unemployment"] = None

        return indicators

    def _calc_regime(self, indicators: dict[str, Any]) -> str:
        """VIX와 국채 스프레드를 기반으로 시장 레짐을 판단한다.

        Args:
            indicators: 조회된 지표 딕셔너리.

        Returns:
            레짐 문자열 (strong_bull, mild_bull, neutral, mild_bear, strong_bear, crisis, unknown).
        """
        vix_data = indicators.get("vix")
        spread_data = indicators.get("spread_10y2y")

        vix_val: float | None = None
        spread_val: float | None = None

        if isinstance(vix_data, dict):
            vix_val = vix_data.get("value")
        if isinstance(spread_data, dict):
            spread_val = spread_data.get("value")

        if vix_val is None:
            return "unknown"

        if vix_val >= _REGIME_VIX_EXTREME:
            return "crisis"
        if vix_val >= _REGIME_VIX_HIGH:
            if spread_val is not None and spread_val < _REGIME_SPREAD_INVERTED:
                return "strong_bear"
            return "mild_bear"
        if spread_val is not None and spread_val < _REGIME_SPREAD_FLAT:
            return "neutral"
        if vix_val < 15.0:
            return "strong_bull"
        return "mild_bull"

    async def _save_to_db(self, indicators: dict[str, Any]) -> None:
        """지표 결과를 DB IndicatorHistory 테이블에 저장한다.

        각 지표를 별도 행으로 저장하며, 조회 실패(None)인 지표는 건너뛴다.
        ticker는 "MACRO"로 고정한다.

        Args:
            indicators: 정규화된 지표 딕셔너리.
        """
        now = datetime.now(timezone.utc)
        rows: list[IndicatorHistory] = []

        # (지표명, 값 추출 함수, 메타데이터 추출 함수) 정의
        save_specs: list[tuple[str, Any, Any]] = [
            ("vix", lambda d: d.get("value"), lambda d: {"level": d.get("level")}),
            ("fear_greed", lambda d: float(d.get("score", 0)), lambda d: {
                "label": d.get("label"),
                "rating_en": d.get("rating_en"),
                "source": d.get("source"),
            }),
            ("fed_rate", lambda d: d.get("value"), lambda d: {
                "date": d.get("date"),
                "previous": d.get("previous"),
            }),
            ("cpi", lambda d: d.get("value"), lambda d: {
                "date": d.get("date"),
                "previous": d.get("previous"),
                "change": d.get("change"),
            }),
            ("spread_10y2y", lambda d: d.get("value"), lambda d: {
                "signal": d.get("signal"),
                "date": d.get("date"),
            }),
            ("yield_10y", lambda d: d.get("value"), lambda d: {"date": d.get("date")}),
            ("yield_2y", lambda d: d.get("value"), lambda d: {"date": d.get("date")}),
            ("unemployment", lambda d: d.get("value"), lambda d: {
                "date": d.get("date"),
                "previous": d.get("previous"),
                "change": d.get("change"),
            }),
        ]

        for indicator_name, val_fn, meta_fn in save_specs:
            data = indicators.get(indicator_name)
            if not isinstance(data, dict):
                continue
            try:
                val = val_fn(data)
                if val is None:
                    continue
                meta = meta_fn(data)
                rows.append(
                    IndicatorHistory(
                        ticker="MACRO",
                        indicator_name=indicator_name,
                        value=float(val),
                        recorded_at=now,
                        metadata_=meta,
                    )
                )
            except Exception as exc:
                logger.warning("지표 행 생성 실패 (%s): %s", indicator_name, exc)

        # 레짐 저장
        regime_val = indicators.get("regime")
        if regime_val is not None:
            regime_score = {
                "strong_bull": 1.0,
                "mild_bull": 0.75,
                "neutral": 0.5,
                "mild_bear": 0.25,
                "strong_bear": 0.1,
                "crisis": 0.0,
                "unknown": 0.5,
            }.get(str(regime_val), 0.5)
            rows.append(
                IndicatorHistory(
                    ticker="MACRO",
                    indicator_name="regime",
                    value=regime_score,
                    recorded_at=now,
                    metadata_={"regime": regime_val},
                )
            )

        if not rows:
            logger.warning("저장할 지표 행이 없음")
            return

        try:
            async with get_session() as session:
                session.add_all(rows)
                await session.commit()
            logger.info("지표 %d개 DB 저장 완료", len(rows))
        except Exception as exc:
            logger.error("DB 저장 중 예외: %s", exc, exc_info=True)
            raise

    def _detect_changes(self, indicators: dict[str, Any]) -> dict[str, Any]:
        """이전 조회 결과와 현재 결과를 비교하여 유의미한 변화를 감지한다.

        Args:
            indicators: 현재 조회 결과.

        Returns:
            변화가 있는 지표들의 {지표명: (이전값, 현재값)} 딕셔너리.
        """
        if not self._last_results:
            return {"initial": True}

        changes: dict[str, Any] = {}

        # VIX 변화 감지
        try:
            cur_vix = indicators.get("vix", {}) or {}
            prev_vix = self._last_results.get("vix", {}) or {}
            cv = cur_vix.get("value")
            pv = prev_vix.get("value")
            if cv is not None and pv is not None:
                diff = abs(float(cv) - float(pv))
                if diff >= _CHANGE_THRESHOLD_VIX:
                    changes["vix"] = {"prev": pv, "curr": cv, "diff": round(diff, 2)}
        except Exception:
            pass

        # Fear&Greed 변화 감지
        try:
            cur_fg = indicators.get("fear_greed", {}) or {}
            prev_fg = self._last_results.get("fear_greed", {}) or {}
            cs = cur_fg.get("score")
            ps = prev_fg.get("score")
            if cs is not None and ps is not None:
                diff = abs(int(cs) - int(ps))
                if diff >= _CHANGE_THRESHOLD_FEAR_GREED:
                    changes["fear_greed"] = {"prev": ps, "curr": cs, "diff": diff}
        except Exception:
            pass

        # 스프레드 변화 감지
        try:
            cur_sp = indicators.get("spread_10y2y", {}) or {}
            prev_sp = self._last_results.get("spread_10y2y", {}) or {}
            cv = cur_sp.get("value")
            pv = prev_sp.get("value")
            if cv is not None and pv is not None:
                diff = abs(float(cv) - float(pv))
                if diff >= _CHANGE_THRESHOLD_SPREAD:
                    changes["spread_10y2y"] = {"prev": pv, "curr": cv, "diff": round(diff, 3)}
        except Exception:
            pass

        # Fed Rate 변화 감지
        try:
            cur_fed = indicators.get("fed_rate", {}) or {}
            prev_fed = self._last_results.get("fed_rate", {}) or {}
            cv = cur_fed.get("value")
            pv = prev_fed.get("value")
            if cv is not None and pv is not None:
                diff = abs(float(cv) - float(pv))
                if diff >= _CHANGE_THRESHOLD_FED:
                    changes["fed_rate"] = {"prev": pv, "curr": cv, "diff": round(diff, 3)}
        except Exception:
            pass

        # 레짐 변화 감지
        cur_regime = indicators.get("regime")
        prev_regime = self._last_results.get("regime")
        if cur_regime and prev_regime and cur_regime != prev_regime:
            changes["regime"] = {"prev": prev_regime, "curr": cur_regime}

        return changes

    def _build_analysis_prompt(
        self,
        indicators: dict[str, Any],
        changes: dict[str, Any],
    ) -> str:
        """Sonnet 분석용 프롬프트를 생성한다.

        Args:
            indicators: 현재 지표 딕셔너리.
            changes: 감지된 변화 딕셔너리.

        Returns:
            분석 프롬프트 문자열.
        """
        def safe_val(d: Any, key: str, default: str = "N/A") -> str:
            if isinstance(d, dict):
                v = d.get(key)
                return str(v) if v is not None else default
            return default

        vix = indicators.get("vix") or {}
        fg = indicators.get("fear_greed") or {}
        fed = indicators.get("fed_rate") or {}
        cpi = indicators.get("cpi") or {}
        sp = indicators.get("spread_10y2y") or {}
        y10 = indicators.get("yield_10y") or {}
        y2 = indicators.get("yield_2y") or {}
        unemp = indicators.get("unemployment") or {}
        regime = indicators.get("regime", "unknown")

        changes_text = json.dumps(changes, ensure_ascii=False, default=str)

        prompt = f"""다음은 미국 주요 거시경제 지표 현황입니다.

## 현재 지표값
- VIX (변동성): {safe_val(vix, 'value')} ({safe_val(vix, 'level')})
- Fear & Greed: {safe_val(fg, 'score')}점 / {safe_val(fg, 'label')}
- 연방기금금리: {safe_val(fed, 'value')}%
- CPI (소비자물가): {safe_val(cpi, 'value')} (전월 {safe_val(cpi, 'previous')}, 변화 {safe_val(cpi, 'change')})
- 10Y-2Y 국채 스프레드: {safe_val(sp, 'value')}% ({safe_val(sp, 'signal')})
- 10년 국채 수익률: {safe_val(y10, 'value')}%
- 2년 국채 수익률: {safe_val(y2, 'value')}%
- 실업률: {safe_val(unemp, 'value')}% (전월 {safe_val(unemp, 'previous')})
- 시장 레짐: {regime}

## 이전 대비 변화
{changes_text}

## 요청
위 지표를 종합하여 다음을 작성해주세요:
1. 현재 시장 상황 요약 (1-2문장, 한국어)
2. 레버리지 ETF 트레이딩 관점의 시사점 (1-2문장, 한국어)

간결하고 실용적으로 작성하세요. 총 3-4문장 이내로 제한합니다."""

        return prompt

    async def _analyze_with_sonnet(
        self,
        indicators: dict[str, Any],
    ) -> str | None:
        """지표 변화를 Sonnet으로 분석한다.

        claude_client가 없으면 None을 반환한다.
        변화가 없으면 이전 분석 결과를 유지한다.

        Args:
            indicators: 현재 조회된 지표 딕셔너리.

        Returns:
            Sonnet 분석 결과 문자열 또는 None.
        """
        if self._claude_client is None:
            return None

        changes = self._detect_changes(indicators)
        if not changes:
            logger.debug("지표 변화 없음 - Sonnet 분석 건너뜀")
            return self._last_analysis

        prompt = self._build_analysis_prompt(indicators, changes)

        try:
            result = await self._claude_client.call(
                prompt=prompt,
                task_type="delta_analysis",  # Sonnet 모델로 라우팅됨
                system_prompt=(
                    "당신은 미국 주식 시장과 거시경제 지표를 분석하는 전문가입니다. "
                    "레버리지 ETF 트레이딩을 위한 실용적이고 간결한 분석을 제공합니다."
                ),
                max_tokens=400,
                use_cache=False,
            )
            analysis: str = result.get("content", "").strip()
            if analysis:
                logger.info("Sonnet 분석 완료 (chars=%d)", len(analysis))
                return analysis
        except Exception as exc:
            logger.warning("Sonnet 분석 요청 실패: %s", exc)

        return self._last_analysis

    def get_latest(self) -> dict[str, Any]:
        """최신 크롤링 결과를 반환한다 (인메모리 캐시).

        Returns:
            마지막으로 크롤링된 지표 딕셔너리.
            updated_at 키에 마지막 갱신 시각이 포함된다.
        """
        if not self._last_results:
            return {
                "indicators": {},
                "updated_at": None,
                "message": "아직 크롤링이 수행되지 않았습니다.",
            }

        return {
            "indicators": self._last_results,
            "updated_at": (
                self._last_update.isoformat() if self._last_update else None
            ),
        }

    def get_last_analysis(self) -> str | None:
        """최신 Sonnet 분석 결과를 반환한다.

        Returns:
            분석 텍스트 또는 None (분석 미수행 또는 claude_client 미설정).
        """
        return self._last_analysis


async def _noop() -> None:
    """FRED API 키 미설정 시 사용하는 빈 코루틴이다."""
    return None

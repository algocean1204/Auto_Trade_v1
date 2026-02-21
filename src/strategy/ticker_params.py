"""종목별 AI 최적화 전략 파라미터 관리 모듈.

AI가 각 종목의 RSI 패턴, 변동성, 섹터 특성을 분석하여
최적 전략 파라미터를 추천한다. 유저는 필요한 종목만 오버라이드한다.

우선순위: user_override > ai_recommended > global_default
"""

from __future__ import annotations

import asyncio
import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from src.analysis.prompts import build_ticker_optimization_prompt
from src.strategy.etf_universe import (
    BULL_2X_UNIVERSE,
    BEAR_2X_UNIVERSE,
    INDIVIDUAL_STOCK_UNIVERSE,
    SECTOR_LEVERAGED_UNIVERSE,
    CRYPTO_LEVERAGED_UNIVERSE,
    get_ticker_info,
)
from src.strategy.params import StrategyParams
from src.utils.logger import get_logger
from src.utils.ticker_mapping import get_sector

if TYPE_CHECKING:
    from src.analysis.claude_client import ClaudeClient
    from src.indicators.calculator import TechnicalCalculator

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

# 종목별 파라미터 파일 경로
_TICKER_PARAMS_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "ticker_params.json"

# AI 분석 배치 크기 (한 번에 분석할 종목 수)
_AI_BATCH_SIZE: int = 10

# 종목별로 오버라이드 가능한 파라미터 키 목록
_OVERRIDABLE_PARAMS: set[str] = {
    "take_profit_pct",
    "stop_loss_pct",
    "trailing_stop_pct",
    "min_confidence",
    "max_position_pct",
    "max_hold_days",
    "eod_close",
}


class TickerParamsManager:
    """종목별 AI 최적화 전략 파라미터 관리 클래스.

    AI가 각 종목의 RSI 패턴, 변동성, 섹터 특성을 분석하여
    최적 전략 파라미터를 추천한다. 유저는 필요한 종목만 오버라이드한다.

    Attributes:
        _params_path: ticker_params.json 파일 경로.
        _ticker_params: 종목별 파라미터 딕셔너리.
        _global_params: 글로벌 전략 파라미터 (폴백용).
        _claude_client: Claude AI 클라이언트.
        _indicator_calculator: 기술적 지표 계산기.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        strategy_params: StrategyParams,
        indicator_calculator: TechnicalCalculator,
    ) -> None:
        """TickerParamsManager를 초기화한다.

        Args:
            claude_client: Claude AI 클라이언트 인스턴스.
            strategy_params: 글로벌 전략 파라미터 인스턴스.
            indicator_calculator: 기술적 지표 계산기 인스턴스.
        """
        self._params_path = _TICKER_PARAMS_PATH
        self._ticker_params: dict[str, dict[str, Any]] = {}
        self._global_params = strategy_params
        self._claude_client = claude_client
        self._indicator_calculator = indicator_calculator

        self._load()
        logger.info(
            "TickerParamsManager 초기화 완료 | 저장된 종목 수: %d | 경로: %s",
            len(self._ticker_params),
            self._params_path,
        )

    # ------------------------------------------------------------------
    # AI 최적화 메서드
    # ------------------------------------------------------------------

    async def ai_optimize_ticker(
        self,
        ticker: str,
        kis_client: Any,
    ) -> dict[str, Any]:
        """단일 종목의 최적 파라미터를 AI가 분석하여 추천한다.

        1. KIS API로 최근 가격 데이터 조회
        2. RSI(7/14/21) + Signal(9) 계산
        3. 변동성, 섹터 정보 수집
        4. Claude에게 분석 요청 -> 종목별 최적 파라미터 추천

        Args:
            ticker: 분석할 종목 티커.
            kis_client: KIS API 클라이언트 인스턴스.

        Returns:
            AI 분석 결과 딕셔너리.
        """
        try:
            ticker = ticker.upper()
            ticker_info = get_ticker_info(ticker)
            if ticker_info is None:
                logger.warning("유효하지 않은 티커: %s, AI 분석 스킵", ticker)
                return {}

            # 가격 데이터 조회
            from src.indicators.data_fetcher import PriceDataFetcher
            fetcher = PriceDataFetcher(kis_client)
            df = await fetcher.get_daily_prices(ticker, days=100)

            if df is None or df.empty or len(df) < 50:
                logger.warning(
                    "종목 %s: 가격 데이터 부족 (%d rows), AI 분석 스킵",
                    ticker,
                    len(df) if df is not None else 0,
                )
                return {}

            # 기술적 지표 계산
            triple_rsi = self._indicator_calculator.calculate_triple_rsi(df)
            atr = self._indicator_calculator.calculate_atr(df)
            bollinger = self._indicator_calculator.calculate_bollinger(df)

            # 변동성 계산 (일간 수익률의 표준편차)
            daily_returns = df["Close"].pct_change().dropna()
            avg_daily_volatility = round(float(daily_returns.std() * 100), 2)
            current_price = float(df["Close"].iloc[-1])

            # 섹터 정보 조회
            sector_info = get_sector(ticker)
            sector_name = sector_info["sector_key"] if sector_info else "unknown"

            # 레버리지/방향 정보
            leverage_type = "individual"
            if ticker in BULL_2X_UNIVERSE:
                leverage_type = "2x_bull"
            elif ticker in BEAR_2X_UNIVERSE:
                leverage_type = "2x_bear"
            elif ticker in SECTOR_LEVERAGED_UNIVERSE:
                leverage_type = "3x_leveraged"
            elif ticker in CRYPTO_LEVERAGED_UNIVERSE:
                leverage_type = "2x_crypto"

            # 리스크 등급 판정
            if avg_daily_volatility > 5.0:
                risk_grade = "VERY_HIGH"
            elif avg_daily_volatility > 3.0:
                risk_grade = "HIGH"
            elif avg_daily_volatility > 2.0:
                risk_grade = "MEDIUM"
            else:
                risk_grade = "LOW"

            analysis = {
                "avg_daily_volatility": avg_daily_volatility,
                "rsi_7_current": triple_rsi["rsi_7"]["rsi"],
                "rsi_14_current": triple_rsi["rsi_14"]["rsi"],
                "rsi_21_current": triple_rsi["rsi_21"]["rsi"],
                "rsi_consensus": triple_rsi.get("consensus", "neutral"),
                "rsi_divergence": triple_rsi.get("divergence", False),
                "atr_14": atr,
                "bollinger_bandwidth": bollinger.get("bandwidth", 0.0),
                "current_price": current_price,
                "sector": sector_name,
                "leverage": leverage_type,
                "risk_grade": risk_grade,
                "name": ticker_info.get("name", ticker),
                "underlying": ticker_info.get("underlying", ""),
            }

            return analysis

        except Exception as exc:
            logger.error("종목 %s AI 분석 데이터 수집 실패: %s", ticker, exc)
            return {}

    async def ai_optimize_all(
        self,
        kis_client: Any,
    ) -> dict[str, Any]:
        """전체 유니버스 종목의 파라미터를 AI가 일괄 분석한다.

        준비 단계(preparation)에서 1일 1회 호출된다.
        배치 단위로 종목을 분석하여 API 비용을 절감한다.

        Args:
            kis_client: KIS API 클라이언트 인스턴스.

        Returns:
            전체 분석 결과 요약.
        """
        logger.info("========== AI 종목별 파라미터 최적화 시작 ==========")

        # 활성 종목 목록 수집
        active_tickers: list[str] = []
        for universe in [
            BULL_2X_UNIVERSE,
            BEAR_2X_UNIVERSE,
            INDIVIDUAL_STOCK_UNIVERSE,
            SECTOR_LEVERAGED_UNIVERSE,
            CRYPTO_LEVERAGED_UNIVERSE,
        ]:
            for ticker, info in universe.items():
                if info.get("enabled", False):
                    active_tickers.append(ticker)

        active_tickers = sorted(set(active_tickers))
        total = len(active_tickers)
        logger.info("활성 종목 %d개 대상 AI 분석 시작", total)

        # 각 종목의 분석 데이터 수집 (순차적으로 KIS API 호출)
        ticker_analyses: dict[str, dict] = {}
        for i, ticker in enumerate(active_tickers):
            logger.debug("분석 데이터 수집 [%d/%d]: %s", i + 1, total, ticker)
            analysis = await self.ai_optimize_ticker(ticker, kis_client)
            if analysis:
                ticker_analyses[ticker] = analysis

        if not ticker_analyses:
            logger.warning("분석 가능한 종목이 없다. AI 최적화 종료.")
            return {"status": "no_data", "analyzed": 0, "total": total}

        # 배치 단위로 Claude에게 분석 요청
        analyzed_count = 0
        batch_tickers = list(ticker_analyses.keys())

        for batch_start in range(0, len(batch_tickers), _AI_BATCH_SIZE):
            batch_end = min(batch_start + _AI_BATCH_SIZE, len(batch_tickers))
            batch = batch_tickers[batch_start:batch_end]
            batch_data = {t: ticker_analyses[t] for t in batch}

            logger.info(
                "AI 배치 분석 [%d~%d/%d]: %s",
                batch_start + 1,
                batch_end,
                len(batch_tickers),
                ", ".join(batch),
            )

            try:
                prompt = build_ticker_optimization_prompt(
                    ticker_analyses=batch_data,
                    global_params=self._global_params.to_dict(),
                )
                from src.analysis.prompts import get_system_prompt
                system_prompt = get_system_prompt("trading_decision")

                result = await self._claude_client.call_json(
                    prompt=prompt,
                    task_type="trading_decision",
                    system_prompt=system_prompt,
                    max_tokens=8192,
                    use_cache=False,
                )

                # 결과 파싱 및 저장
                if isinstance(result, dict):
                    recommendations = result.get("recommendations", result)
                    if isinstance(recommendations, dict):
                        self._apply_ai_recommendations(recommendations, batch_data)
                        analyzed_count += len(recommendations)
                elif isinstance(result, list):
                    # 리스트 형태로 반환된 경우 딕셔너리로 변환
                    for item in result:
                        if isinstance(item, dict) and "ticker" in item:
                            t = item["ticker"].upper()
                            recs = {t: item}
                            analysis_for_t = {t: batch_data.get(t, {})}
                            self._apply_ai_recommendations(recs, analysis_for_t)
                            analyzed_count += 1

            except Exception as exc:
                logger.error(
                    "AI 배치 분석 실패 (batch %d~%d): %s",
                    batch_start + 1,
                    batch_end,
                    exc,
                )

        # 분석 결과 저장
        self._save()

        summary = {
            "status": "completed",
            "analyzed": analyzed_count,
            "total_active": total,
            "total_with_data": len(ticker_analyses),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        logger.info(
            "========== AI 종목별 파라미터 최적화 완료: %d/%d 종목 분석 ==========",
            analyzed_count,
            total,
        )
        return summary

    def _apply_ai_recommendations(
        self,
        recommendations: dict[str, Any],
        analyses: dict[str, dict],
    ) -> None:
        """AI 추천 결과를 내부 저장소에 적용한다.

        Args:
            recommendations: 종목별 AI 추천 파라미터.
            analyses: 종목별 분석 데이터.
        """
        now = datetime.now(tz=timezone.utc).isoformat()

        for ticker, rec in recommendations.items():
            ticker = ticker.upper()
            if not isinstance(rec, dict):
                continue

            # 추천 파라미터 추출 (오버라이드 가능한 키만)
            ai_recommended: dict[str, Any] = {}
            for key in _OVERRIDABLE_PARAMS:
                if key in rec:
                    ai_recommended[key] = rec[key]

            if not ai_recommended:
                logger.debug("종목 %s: AI 추천 파라미터 없음, 스킵", ticker)
                continue

            # 기존 데이터 보존 (user_override)
            existing = self._ticker_params.get(ticker, {})
            user_override = existing.get("user_override", {})
            user_updated_at = existing.get("user_updated_at")

            self._ticker_params[ticker] = {
                "ai_recommended": ai_recommended,
                "ai_reasoning": rec.get("reasoning", rec.get("ai_reasoning", "")),
                "ai_analysis": analyses.get(ticker, {}),
                "ai_updated_at": now,
                "user_override": user_override,
                "user_updated_at": user_updated_at,
            }

            logger.debug(
                "종목 %s: AI 추천 적용 | tp=%.1f%%, sl=%.1f%%, ts=%.1f%%",
                ticker,
                ai_recommended.get("take_profit_pct", 0),
                ai_recommended.get("stop_loss_pct", 0),
                ai_recommended.get("trailing_stop_pct", 0),
            )

    # ------------------------------------------------------------------
    # 파라미터 조회 메서드
    # ------------------------------------------------------------------

    def get_effective_params(self, ticker: str) -> dict[str, Any]:
        """종목의 유효 파라미터를 반환한다.

        우선순위: user_override > ai_recommended > global_default.

        Args:
            ticker: 종목 티커.

        Returns:
            유효 파라미터 딕셔너리. 모든 오버라이드 가능한 키를 포함한다.
        """
        ticker = ticker.upper()
        global_params = self._global_params.to_dict()

        # 글로벌 기본값으로 시작
        effective: dict[str, Any] = {}
        for key in _OVERRIDABLE_PARAMS:
            effective[key] = global_params.get(key)

        # 종목별 데이터가 있으면 AI 추천값으로 덮어쓰기
        ticker_data = self._ticker_params.get(ticker)
        if ticker_data is not None:
            ai_rec = ticker_data.get("ai_recommended", {})
            for key in _OVERRIDABLE_PARAMS:
                if key in ai_rec:
                    effective[key] = ai_rec[key]

            # 유저 오버라이드가 있으면 최종 덮어쓰기
            user_override = ticker_data.get("user_override", {})
            for key in _OVERRIDABLE_PARAMS:
                if key in user_override:
                    effective[key] = user_override[key]

        return effective

    def get_effective_param(self, ticker: str, param_name: str) -> Any:
        """종목의 특정 유효 파라미터 값을 반환한다.

        Args:
            ticker: 종목 티커.
            param_name: 파라미터 키 이름.

        Returns:
            유효 파라미터 값.
        """
        effective = self.get_effective_params(ticker)
        if param_name in effective:
            return effective[param_name]
        # 오버라이드 불가능한 파라미터는 글로벌에서 조회
        return self._global_params.get_param(param_name)

    def set_user_override(
        self,
        ticker: str,
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        """유저가 특정 종목의 파라미터를 오버라이드한다.

        Args:
            ticker: 종목 티커.
            overrides: 오버라이드할 파라미터 딕셔너리.

        Returns:
            업데이트된 유효 파라미터.

        Raises:
            ValueError: 유효하지 않은 파라미터 키가 포함된 경우.
        """
        ticker = ticker.upper()
        now = datetime.now(tz=timezone.utc).isoformat()

        # 유효한 키만 허용
        invalid_keys = set(overrides.keys()) - _OVERRIDABLE_PARAMS
        if invalid_keys:
            raise ValueError(
                f"오버라이드 불가능한 파라미터: {', '.join(invalid_keys)}. "
                f"허용 키: {', '.join(sorted(_OVERRIDABLE_PARAMS))}"
            )

        # 기존 데이터가 없으면 빈 구조 생성
        if ticker not in self._ticker_params:
            self._ticker_params[ticker] = {
                "ai_recommended": {},
                "ai_reasoning": "",
                "ai_analysis": {},
                "ai_updated_at": None,
                "user_override": {},
                "user_updated_at": None,
            }

        # 오버라이드 적용
        existing_override = self._ticker_params[ticker].get("user_override", {})
        existing_override.update(overrides)
        self._ticker_params[ticker]["user_override"] = existing_override
        self._ticker_params[ticker]["user_updated_at"] = now

        self._save()

        logger.info(
            "종목 %s: 유저 오버라이드 설정 | %s",
            ticker,
            json.dumps(overrides, default=str),
        )

        return self.get_effective_params(ticker)

    def clear_user_override(
        self,
        ticker: str,
        param_name: str | None = None,
    ) -> dict[str, Any]:
        """유저 오버라이드를 제거한다 (AI 추천값으로 복귀).

        Args:
            ticker: 종목 티커.
            param_name: 특정 파라미터 키. None이면 전체 오버라이드 제거.

        Returns:
            업데이트된 유효 파라미터.
        """
        ticker = ticker.upper()

        ticker_data = self._ticker_params.get(ticker)
        if ticker_data is None:
            logger.debug("종목 %s: 오버라이드 데이터 없음", ticker)
            return self.get_effective_params(ticker)

        if param_name is not None:
            # 특정 키만 제거
            user_override = ticker_data.get("user_override", {})
            if param_name in user_override:
                del user_override[param_name]
                ticker_data["user_override"] = user_override
                logger.info("종목 %s: 유저 오버라이드 제거 | key=%s", ticker, param_name)
        else:
            # 전체 오버라이드 제거
            ticker_data["user_override"] = {}
            ticker_data["user_updated_at"] = None
            logger.info("종목 %s: 유저 오버라이드 전체 제거", ticker)

        self._save()
        return self.get_effective_params(ticker)

    def get_ticker_detail(self, ticker: str) -> dict[str, Any]:
        """종목의 AI 분석 결과 + 추천 파라미터 + 유저 오버라이드 전체를 반환한다.

        Args:
            ticker: 종목 티커.

        Returns:
            종목 상세 딕셔너리.
        """
        ticker = ticker.upper()
        ticker_data = self._ticker_params.get(ticker, {})

        effective = self.get_effective_params(ticker)
        global_params = self._global_params.to_dict()

        # 각 파라미터의 출처(source) 표시
        param_sources: dict[str, str] = {}
        for key in _OVERRIDABLE_PARAMS:
            user_override = ticker_data.get("user_override", {})
            ai_rec = ticker_data.get("ai_recommended", {})
            if key in user_override:
                param_sources[key] = "user_override"
            elif key in ai_rec:
                param_sources[key] = "ai_recommended"
            else:
                param_sources[key] = "global_default"

        return {
            "ticker": ticker,
            "effective": effective,
            "param_sources": param_sources,
            "ai_recommended": ticker_data.get("ai_recommended", {}),
            "ai_reasoning": ticker_data.get("ai_reasoning", ""),
            "ai_analysis": ticker_data.get("ai_analysis", {}),
            "ai_updated_at": ticker_data.get("ai_updated_at"),
            "user_override": ticker_data.get("user_override", {}),
            "user_updated_at": ticker_data.get("user_updated_at"),
            "global_default": {
                key: global_params.get(key) for key in _OVERRIDABLE_PARAMS
            },
        }

    def get_all_ticker_params(self) -> dict[str, Any]:
        """전체 종목 파라미터 요약을 반환한다.

        Returns:
            종목별 요약 딕셔너리.
        """
        summary: dict[str, Any] = {}

        for ticker, data in self._ticker_params.items():
            effective = self.get_effective_params(ticker)
            has_override = bool(data.get("user_override", {}))
            has_ai = bool(data.get("ai_recommended", {}))

            summary[ticker] = {
                "effective": effective,
                "has_ai_recommendation": has_ai,
                "has_user_override": has_override,
                "ai_updated_at": data.get("ai_updated_at"),
                "user_updated_at": data.get("user_updated_at"),
                "risk_grade": data.get("ai_analysis", {}).get("risk_grade", "UNKNOWN"),
                "sector": data.get("ai_analysis", {}).get("sector", "unknown"),
            }

        return {
            "tickers": summary,
            "total_count": len(summary),
            "with_ai": sum(
                1 for d in summary.values() if d["has_ai_recommendation"]
            ),
            "with_override": sum(
                1 for d in summary.values() if d["has_user_override"]
            ),
        }

    # ------------------------------------------------------------------
    # 파일 I/O
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """data/ticker_params.json에 저장한다."""
        try:
            # 디렉토리가 없으면 생성
            self._params_path.parent.mkdir(parents=True, exist_ok=True)

            def _sync_save() -> None:
                try:
                    f = open(self._params_path, "r+", encoding="utf-8")
                except FileNotFoundError:
                    f = open(self._params_path, "w", encoding="utf-8")
                with f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    try:
                        f.seek(0)
                        f.truncate()
                        json.dump(
                            self._ticker_params,
                            f,
                            indent=2,
                            ensure_ascii=False,
                            default=str,
                        )
                        f.write("\n")
                    finally:
                        fcntl.flock(f, fcntl.LOCK_UN)

            # asyncio 이벤트 루프가 실행 중이면 to_thread 사용
            try:
                loop = asyncio.get_running_loop()
                # 이벤트 루프가 실행 중이면 바로 동기 호출 (이미 메인 스레드)
                _sync_save()
            except RuntimeError:
                _sync_save()

            logger.debug(
                "ticker_params.json 저장 완료: %d 종목",
                len(self._ticker_params),
            )
        except OSError as exc:
            logger.error("ticker_params.json 저장 실패: %s", exc)

    def _load(self) -> None:
        """data/ticker_params.json에서 로드한다."""
        if not self._params_path.exists():
            logger.info(
                "ticker_params.json 파일이 없다 (%s), 빈 상태로 시작",
                self._params_path,
            )
            return

        try:
            def _sync_load() -> dict:
                with open(self._params_path, "r", encoding="utf-8") as f:
                    fcntl.flock(f, fcntl.LOCK_SH)
                    try:
                        content = f.read()
                        if not content.strip():
                            return {}
                        return json.loads(content)
                    finally:
                        fcntl.flock(f, fcntl.LOCK_UN)

            data = _sync_load()
            if isinstance(data, dict):
                self._ticker_params = data
                logger.info(
                    "ticker_params.json 로드 완료: %d 종목",
                    len(self._ticker_params),
                )
            else:
                logger.warning("ticker_params.json 형식 오류: dict가 아닌 %s", type(data))
                self._ticker_params = {}

        except (json.JSONDecodeError, OSError) as exc:
            logger.error("ticker_params.json 로드 실패: %s", exc)
            self._ticker_params = {}

"""과거분석팀 / 종목분석팀 모듈.

2021년부터 현재까지 주간 단위로 역사적 뉴스와 시장 데이터를 분석한다.
1리더 + 3분석관 구조로 기업별 타임라인을 생성하여 DB에 저장한다.
현재 시점에 도달하면 종목분석팀으로 전환하여 실시간 분석을 수행한다.

분석 데이터 소스는 Claude의 훈련 데이터(학습된 지식)를 활용하며,
별도의 외부 크롤링 없이 효율적으로 역사적 분석을 수행한다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select

from src.analysis.prompts import (
    build_historical_company_prompt,
    build_historical_market_prompt,
    build_historical_sector_prompt,
    build_historical_timeline_prompt,
    build_realtime_stock_analysis_prompt,
    get_system_prompt,
)
from src.db.connection import get_session
from src.db.models import Article, HistoricalAnalysis, HistoricalAnalysisProgress
from src.utils.logger import get_logger
from src.utils.ticker_mapping import SECTOR_TICKERS

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

# 과거 분석 시작 날짜 (2021년 1월 첫 번째 월요일)
_HISTORICAL_START_DATE: date = date(2021, 1, 4)

# 주간 분석 간 대기 시간 (초) — API 비용 관리용
_INTER_WEEK_DELAY: int = 30

# 분석관 호출 간 대기 시간 (초) — rate limit 방지
_INTER_ANALYST_DELAY: int = 5

# 실시간 모드에서 종목 간 대기 시간 (초)
_INTER_TICKER_DELAY: int = 60

# 최대 출력 토큰 수 (분석관)
_ANALYST_MAX_TOKENS: int = 2048

# 최대 출력 토큰 수 (리더 종합)
_LEADER_MAX_TOKENS: int = 3072

# 실시간 분석 최대 출력 토큰 수
_REALTIME_MAX_TOKENS: int = 2048

# get_historical_context 기본 조회 주 수
_DEFAULT_CONTEXT_WEEKS: int = 4

# 최근 뉴스 조회 제한
_RECENT_NEWS_LIMIT: int = 10


def _get_all_tickers() -> list[str]:
    """분석 대상 전체 종목 목록을 반환한다.

    SECTOR_TICKERS에서 모든 섹터의 종목을 수집한다.
    """
    tickers: set[str] = set()
    for sector_info in SECTOR_TICKERS.values():
        for t in sector_info.get("tickers", []):
            tickers.add(t)
    return sorted(tickers)


def _get_sector_names() -> list[str]:
    """분석 대상 섹터 한글명 목록을 반환한다."""
    return [info["name_kr"] for info in SECTOR_TICKERS.values()]


def _get_sector_ticker_map() -> dict[str, list[str]]:
    """섹터 한글명 → 종목 목록 딕셔너리를 반환한다."""
    return {
        info["name_kr"]: list(info["tickers"])
        for info in SECTOR_TICKERS.values()
    }


class HistoricalAnalysisTeam:
    """과거분석팀 / 종목분석팀.

    Phase 1 (historical): 2021~현재까지 주간 역사적 분석
    Phase 2 (realtime): 현재 도달 후 실시간 종목 분석

    Attributes:
        client: Claude API 클라이언트.
        _running: 백그라운드 분석 실행 여부.
        _current_mode: "historical" 또는 "realtime".
        _progress: DB에서 로드된 진행 상태.
    """

    def __init__(self, claude_client: Any) -> None:
        """HistoricalAnalysisTeam을 초기화한다.

        Args:
            claude_client: ClaudeClient 인스턴스.
        """
        self.client = claude_client
        self._running: bool = False
        self._current_mode: str = "historical"
        self._progress: HistoricalAnalysisProgress | None = None
        self._current_week: date | None = None
        self._total_weeks_analyzed: int = 0
        self._realtime_ticker_index: int = 0

    async def start_background_analysis(self) -> None:
        """백그라운드 분석 태스크를 시작한다.

        자동매매 시작 시 호출되며, 매매 종료 시까지 계속 실행된다.
        1주일치 분석 -> 저장 -> 다음 주 -> ... 반복
        """
        self._running = True
        logger.info("과거분석팀 백그라운드 태스크 시작")

        try:
            # DB에서 진행 상태 로드
            progress = await self._load_progress()
            if progress and progress.status == "completed":
                self._current_mode = "realtime"
                self._total_weeks_analyzed = progress.total_weeks_analyzed
                logger.info(
                    "과거 분석 이미 완료됨. 종목분석팀(realtime) 모드로 시작 | "
                    "총 %d주 분석 완료",
                    self._total_weeks_analyzed,
                )
            elif progress:
                self._total_weeks_analyzed = progress.total_weeks_analyzed
                logger.info(
                    "이전 진행 상태 로드 완료 | 마지막 완료 주: %s | 총 %d주 분석됨",
                    progress.last_completed_week.isoformat(),
                    self._total_weeks_analyzed,
                )

            start_date = (
                progress.last_completed_week + timedelta(weeks=1)
                if progress and progress.status != "completed"
                else _HISTORICAL_START_DATE
            )

            if self._current_mode == "realtime":
                start_date = date.today()  # 이미 완료됨

            while self._running:
                try:
                    if self._current_mode == "historical":
                        self._current_week = start_date
                        await self._analyze_week(start_date)
                        start_date += timedelta(weeks=1)
                        self._total_weeks_analyzed += 1

                        # 현재 시점 도달 체크
                        if start_date >= date.today():
                            self._current_mode = "realtime"
                            await self._update_progress(
                                start_date - timedelta(weeks=1),
                                "completed",
                                "realtime",
                            )
                            logger.info(
                                "과거 분석 완료! 종목분석팀으로 전환 | 총 %d주 분석",
                                self._total_weeks_analyzed,
                            )
                    else:
                        # Realtime mode: 실시간 종목 심층 분석
                        await self._realtime_stock_analysis()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "과거분석팀 분석 중 오류 (계속 진행): %s", exc, exc_info=True
                    )

                # 다음 분석까지 대기 (API 비용 관리)
                await asyncio.sleep(_INTER_WEEK_DELAY)

        except asyncio.CancelledError:
            logger.info("과거분석팀 백그라운드 태스크 취소됨")
        except Exception as exc:
            logger.error("과거분석팀 치명적 오류: %s", exc, exc_info=True)
        finally:
            self._running = False
            logger.info("과거분석팀 백그라운드 태스크 종료")

    def stop(self) -> None:
        """백그라운드 분석을 중지한다."""
        logger.info("과거분석팀 중지 요청")
        self._running = False

    async def _analyze_week(self, week_start: date) -> None:
        """1주일치 역사적 데이터를 분석한다.

        1. 해당 주간의 주요 뉴스/이벤트를 Claude 학습 데이터에서 분석
        2. 3 분석관이 각각 다른 관점에서 분석
        3. 리더가 종합하여 기업별 타임라인 생성
        4. DB에 저장

        Args:
            week_start: 분석 주간 시작일 (월요일).
        """
        week_end = week_start + timedelta(days=6)
        week_start_str = week_start.isoformat()
        week_end_str = week_end.isoformat()

        logger.info(
            "과거분석팀: %s ~ %s 주간 분석 시작 (모드: %s)",
            week_start_str,
            week_end_str,
            self._current_mode,
        )

        # 이미 분석된 주간인지 확인
        if await self._is_week_analyzed(week_start):
            logger.info("이미 분석된 주간, 건너뜀: %s", week_start_str)
            return

        sectors = _get_sector_names()
        tickers = _get_all_tickers()
        sector_map = _get_sector_ticker_map()

        # 3 analysts analyze in parallel
        market_result, company_result, sector_result = await asyncio.gather(
            self._analyst_market_events(week_start_str, week_end_str, sectors),
            self._analyst_company_actions(week_start_str, week_end_str, tickers),
            self._analyst_sector_dynamics(week_start_str, week_end_str, sector_map),
        )

        # 분석관 호출 후 잠시 대기 (rate limit)
        await asyncio.sleep(_INTER_ANALYST_DELAY)

        # Leader synthesizes
        timeline = await self._leader_create_timeline(
            week_start_str, week_end_str, market_result, company_result, sector_result
        )

        # Save to DB
        await self._save_analysis(week_start, week_end, timeline)
        await self._update_progress(week_start, "running", "historical")

        logger.info(
            "과거분석팀: %s ~ %s 주간 분석 완료 (총 %d주)",
            week_start_str,
            week_end_str,
            self._total_weeks_analyzed + 1,
        )

    async def _analyst_market_events(
        self, start: str, end: str, sectors: list[str]
    ) -> dict:
        """분석관 1: 해당 주간 시장 주요 이벤트를 분석한다.

        Fed 정책, 경제 지표 발표, 지정학적 이벤트, 시장 급등/급락 원인을 다룬다.

        Args:
            start: 주간 시작일 (YYYY-MM-DD).
            end: 주간 종료일 (YYYY-MM-DD).
            sectors: 관심 섹터 목록.

        Returns:
            분석 결과 딕셔너리.
        """
        prompt = build_historical_market_prompt(start, end, sectors)
        system_prompt = get_system_prompt("historical_market")

        try:
            result = await self.client.call_json(
                prompt=prompt,
                task_type="historical_market",
                system_prompt=system_prompt,
                max_tokens=_ANALYST_MAX_TOKENS,
                use_cache=False,
            )
            return result if isinstance(result, dict) else {"raw": result}
        except Exception as exc:
            logger.warning("분석관1 (시장 이벤트) 실패: %s", exc)
            return {"error": str(exc), "macro_events": [], "geopolitical_events": [], "market_moves": []}

    async def _analyst_company_actions(
        self, start: str, end: str, tickers: list[str]
    ) -> dict:
        """분석관 2: 해당 주간 기업 활동을 분석한다.

        실적 발표, M&A, 파트너십, 제품 출시, 경영진 변동을 다룬다.

        Args:
            start: 주간 시작일 (YYYY-MM-DD).
            end: 주간 종료일 (YYYY-MM-DD).
            tickers: 분석 대상 종목 목록.

        Returns:
            분석 결과 딕셔너리.
        """
        prompt = build_historical_company_prompt(start, end, tickers)
        system_prompt = get_system_prompt("historical_company")

        try:
            result = await self.client.call_json(
                prompt=prompt,
                task_type="historical_company",
                system_prompt=system_prompt,
                max_tokens=_ANALYST_MAX_TOKENS,
                use_cache=False,
            )
            return result if isinstance(result, dict) else {"raw": result}
        except Exception as exc:
            logger.warning("분석관2 (기업 활동) 실패: %s", exc)
            return {"error": str(exc), "company_events": []}

    async def _analyst_sector_dynamics(
        self, start: str, end: str, sectors: dict[str, list[str]]
    ) -> dict:
        """분석관 3: 해당 주간 섹터 역학을 분석한다.

        섹터별 자금 흐름, 규제 변화, 공급망 이슈, 기술 트렌드를 다룬다.

        Args:
            start: 주간 시작일 (YYYY-MM-DD).
            end: 주간 종료일 (YYYY-MM-DD).
            sectors: 섹터명-종목목록 딕셔너리.

        Returns:
            분석 결과 딕셔너리.
        """
        prompt = build_historical_sector_prompt(start, end, sectors)
        system_prompt = get_system_prompt("historical_sector")

        try:
            result = await self.client.call_json(
                prompt=prompt,
                task_type="historical_sector",
                system_prompt=system_prompt,
                max_tokens=_ANALYST_MAX_TOKENS,
                use_cache=False,
            )
            return result if isinstance(result, dict) else {"raw": result}
        except Exception as exc:
            logger.warning("분석관3 (섹터 역학) 실패: %s", exc)
            return {"error": str(exc), "sector_dynamics": []}

    async def _leader_create_timeline(
        self,
        start: str,
        end: str,
        market_analysis: dict,
        company_analysis: dict,
        sector_analysis: dict,
    ) -> dict:
        """리더: 3 분석관 결과를 종합하여 기업별 타임라인을 생성한다.

        불필요한 정보는 제거하고, 기업에 대한 중요 정보를 충분히 포함한 타임라인.

        Args:
            start: 주간 시작일 (YYYY-MM-DD).
            end: 주간 종료일 (YYYY-MM-DD).
            market_analysis: 분석관 1 결과.
            company_analysis: 분석관 2 결과.
            sector_analysis: 분석관 3 결과.

        Returns:
            종합 타임라인 딕셔너리.
        """
        prompt = build_historical_timeline_prompt(
            start, end, market_analysis, company_analysis, sector_analysis
        )
        system_prompt = get_system_prompt("historical_timeline")

        try:
            result = await self.client.call_json(
                prompt=prompt,
                task_type="historical_timeline",
                system_prompt=system_prompt,
                max_tokens=_LEADER_MAX_TOKENS,
                use_cache=False,
            )
            return result if isinstance(result, dict) else {"raw": result}
        except Exception as exc:
            logger.error("리더 (타임라인 종합) 실패: %s", exc)
            # 개별 분석 결과를 fallback으로 사용
            return {
                "week": f"{start} ~ {end}",
                "timeline": [],
                "ticker_summaries": {},
                "market_context": f"타임라인 종합 실패: {exc}",
                "investment_insight": "",
                "quality_score": 0.0,
                "_fallback_data": {
                    "market": market_analysis,
                    "company": company_analysis,
                    "sector": sector_analysis,
                },
            }

    async def _realtime_stock_analysis(self) -> None:
        """실시간 모드: 현재 유니버스 종목에 대한 심층 분석을 수행한다.

        과거분석팀이 현재 시점에 도달하면 이 모드로 전환된다.
        종합분석팀과 합류하여 더 깊은 종목 분석을 제공한다.
        라운드 로빈으로 한 종목씩 분석한다.
        """
        tickers = _get_all_tickers()
        if not tickers:
            logger.warning("실시간 분석 대상 종목 없음")
            return

        # 라운드 로빈 인덱스
        idx = self._realtime_ticker_index % len(tickers)
        ticker = tickers[idx]
        self._realtime_ticker_index = idx + 1

        logger.info("종목분석팀: %s 실시간 분석 시작 (%d/%d)", ticker, idx + 1, len(tickers))

        try:
            # 최근 과거 분석 컨텍스트 조회
            recent_context = await self.get_historical_context(ticker=ticker, weeks=4)

            # 최근 뉴스 조회
            recent_news = await self._fetch_recent_news(ticker)

            # 종목 정보
            from src.strategy.etf_universe import get_ticker_info
            ticker_info = get_ticker_info(ticker) or {"ticker": ticker, "name": ticker}

            prompt = build_realtime_stock_analysis_prompt(
                ticker=ticker,
                ticker_info=ticker_info,
                recent_timeline=recent_context,
                recent_news=recent_news,
                indicators={},  # 기술적 지표는 별도 모듈에서 조회
            )
            system_prompt = get_system_prompt("realtime_stock_analysis")

            result = await self.client.call_json(
                prompt=prompt,
                task_type="realtime_stock_analysis",
                system_prompt=system_prompt,
                max_tokens=_REALTIME_MAX_TOKENS,
                use_cache=False,
            )

            # 실시간 분석 결과를 DB에 저장
            today = date.today()
            week_start = today - timedelta(days=today.weekday())  # 이번 주 월요일
            week_end = week_start + timedelta(days=6)

            await self._save_realtime_analysis(week_start, week_end, ticker, result)

            logger.info("종목분석팀: %s 실시간 분석 완료", ticker)

        except Exception as exc:
            logger.error("종목분석팀: %s 분석 실패: %s", ticker, exc, exc_info=True)

        await asyncio.sleep(_INTER_TICKER_DELAY)

    async def get_historical_context(
        self,
        ticker: str | None = None,
        sector: str | None = None,
        weeks: int = _DEFAULT_CONTEXT_WEEKS,
    ) -> str:
        """종합분석팀에서 사용할 과거 분석 컨텍스트를 조회한다.

        Args:
            ticker: 특정 종목 (optional).
            sector: 특정 섹터 (optional).
            weeks: 최근 몇 주 데이터를 가져올지.

        Returns:
            과거 분석 요약 텍스트 (종합분석팀 프롬프트에 삽입용).
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(HistoricalAnalysis)
                    .order_by(desc(HistoricalAnalysis.week_start))
                    .limit(weeks)
                )

                if ticker:
                    stmt = stmt.where(HistoricalAnalysis.ticker == ticker)
                elif sector:
                    stmt = stmt.where(HistoricalAnalysis.sector == sector)

                result = await session.execute(stmt)
                analyses = result.scalars().all()

            if not analyses:
                return "(과거 분석 데이터 없음)"

            context_parts: list[str] = []
            for analysis in reversed(analyses):  # 시간순 정렬
                week_label = f"{analysis.week_start.isoformat()} ~ {analysis.week_end.isoformat()}"
                events = analysis.timeline_events or {}

                # 타임라인에서 핵심 정보 추출
                market_ctx = analysis.market_context or ""
                ticker_summaries = events.get("ticker_summaries", {})
                insight = events.get("investment_insight", "")

                parts = [f"### {week_label}"]
                if market_ctx:
                    parts.append(f"시장 맥락: {market_ctx}")
                if ticker and ticker in ticker_summaries:
                    parts.append(f"{ticker}: {ticker_summaries[ticker]}")
                elif ticker_summaries:
                    # 관련 종목 요약만 포함 (최대 5개)
                    for t, summary in list(ticker_summaries.items())[:5]:
                        parts.append(f"- {t}: {summary}")
                if insight:
                    parts.append(f"투자 인사이트: {insight}")

                context_parts.append("\n".join(parts))

            return "\n\n".join(context_parts)

        except Exception as exc:
            logger.warning("과거 분석 컨텍스트 조회 실패: %s", exc)
            return "(과거 분석 컨텍스트 조회 실패)"

    async def get_progress(self) -> dict[str, Any]:
        """현재 분석 진행 상태를 반환한다.

        Returns:
            진행 상태 딕셔너리.
        """
        progress = await self._load_progress()

        # 전체 분석해야 할 주 수 계산
        today = date.today()
        total_weeks = max(1, (today - _HISTORICAL_START_DATE).days // 7)
        analyzed = progress.total_weeks_analyzed if progress else 0
        pct = min(100.0, round((analyzed / total_weeks) * 100, 1)) if total_weeks > 0 else 0.0

        return {
            "mode": self._current_mode,
            "running": self._running,
            "current_week": self._current_week.isoformat() if self._current_week else None,
            "last_completed_week": (
                progress.last_completed_week.isoformat() if progress else None
            ),
            "total_weeks_analyzed": analyzed,
            "total_weeks_needed": total_weeks,
            "progress_pct": pct,
            "status": progress.status if progress else "not_started",
            "start_date": _HISTORICAL_START_DATE.isoformat(),
        }

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    async def _load_progress(self) -> HistoricalAnalysisProgress | None:
        """DB에서 진행 상태를 로드한다.

        Returns:
            HistoricalAnalysisProgress 또는 None (데이터 없으면).
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(HistoricalAnalysisProgress)
                    .order_by(desc(HistoricalAnalysisProgress.updated_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                progress = result.scalar_one_or_none()
                if progress:
                    # detach from session to avoid lazy-load issues
                    session.expunge(progress)
                return progress
        except Exception as exc:
            logger.warning("진행 상태 로드 실패: %s", exc)
            return None

    async def _update_progress(
        self, week: date, status: str, mode: str
    ) -> None:
        """DB에 진행 상태를 업데이트한다.

        기존 레코드가 있으면 업데이트하고, 없으면 새로 생성한다.

        Args:
            week: 마지막 완료된 주간.
            status: "running" / "completed" / "paused".
            mode: "historical" / "realtime".
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(HistoricalAnalysisProgress)
                    .order_by(desc(HistoricalAnalysisProgress.updated_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                progress = result.scalar_one_or_none()

                if progress:
                    progress.last_completed_week = week
                    progress.total_weeks_analyzed = self._total_weeks_analyzed
                    progress.status = status
                    progress.mode = mode
                    progress.updated_at = datetime.now(tz=timezone.utc)
                else:
                    progress = HistoricalAnalysisProgress(
                        id=str(uuid4()),
                        last_completed_week=week,
                        total_weeks_analyzed=self._total_weeks_analyzed,
                        status=status,
                        mode=mode,
                    )
                    session.add(progress)

        except Exception as exc:
            logger.error("진행 상태 업데이트 실패: %s", exc)

    async def _is_week_analyzed(self, week_start: date) -> bool:
        """해당 주간이 이미 분석되었는지 확인한다.

        Args:
            week_start: 확인할 주간 시작일.

        Returns:
            이미 분석되었으면 True.
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(HistoricalAnalysis.id)
                    .where(HistoricalAnalysis.week_start == week_start)
                    .where(HistoricalAnalysis.ticker.is_(None))
                    .limit(1)
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none() is not None
        except Exception as exc:
            logger.warning("주간 분석 여부 확인 실패: %s", exc)
            return False

    async def _save_analysis(
        self, week_start: date, week_end: date, timeline: dict
    ) -> None:
        """분석 결과를 DB에 저장한다.

        시장 전체 분석 (ticker=None, sector=None)으로 저장하고,
        개별 종목 요약이 있으면 종목별로도 저장한다.

        Args:
            week_start: 주간 시작일.
            week_end: 주간 종료일.
            timeline: 리더가 생성한 종합 타임라인.
        """
        try:
            quality = timeline.get("quality_score", 0.5)
            market_context = timeline.get("market_context", "")
            insight = timeline.get("investment_insight", "")
            ticker_summaries = timeline.get("ticker_summaries", {})

            async with get_session() as session:
                # 시장 전체 분석 저장
                market_analysis = HistoricalAnalysis(
                    id=str(uuid4()),
                    week_start=week_start,
                    week_end=week_end,
                    sector=None,
                    ticker=None,
                    timeline_events=timeline,
                    company_info=None,
                    market_context=market_context,
                    key_metrics=None,
                    analyst_notes=insight,
                    analysis_quality=quality if isinstance(quality, (int, float)) else 0.5,
                    source_count=0,
                )
                session.add(market_analysis)

                # 종목별 요약 저장
                for ticker_sym, summary in ticker_summaries.items():
                    # 종목의 섹터 조회
                    from src.utils.ticker_mapping import get_sector
                    sector_info = get_sector(ticker_sym)
                    sector_key = sector_info["name_kr"] if sector_info else None

                    ticker_analysis = HistoricalAnalysis(
                        id=str(uuid4()),
                        week_start=week_start,
                        week_end=week_end,
                        sector=sector_key,
                        ticker=ticker_sym,
                        timeline_events={"summary": summary},
                        company_info=None,
                        market_context=None,
                        key_metrics=None,
                        analyst_notes=summary if isinstance(summary, str) else json.dumps(summary, ensure_ascii=False, default=str),
                        analysis_quality=quality if isinstance(quality, (int, float)) else 0.5,
                        source_count=0,
                    )
                    session.add(ticker_analysis)

            logger.debug(
                "분석 결과 저장 완료: %s ~ %s | 종목 %d개",
                week_start.isoformat(),
                week_end.isoformat(),
                len(ticker_summaries),
            )
        except Exception as exc:
            logger.error("분석 결과 저장 실패: %s", exc, exc_info=True)

    async def _save_realtime_analysis(
        self, week_start: date, week_end: date, ticker: str, analysis: dict
    ) -> None:
        """실시간 분석 결과를 DB에 저장한다.

        Args:
            week_start: 이번 주 시작일.
            week_end: 이번 주 종료일.
            ticker: 분석 대상 종목.
            analysis: 실시간 분석 결과.
        """
        try:
            from src.utils.ticker_mapping import get_sector
            sector_info = get_sector(ticker)
            sector_name = sector_info["name_kr"] if sector_info else None

            opinion = analysis.get("investment_opinion", {})
            confidence = opinion.get("confidence", 0.5)

            async with get_session() as session:
                record = HistoricalAnalysis(
                    id=str(uuid4()),
                    week_start=week_start,
                    week_end=week_end,
                    sector=sector_name,
                    ticker=ticker,
                    timeline_events=analysis,
                    company_info=None,
                    market_context=analysis.get("current_situation"),
                    key_metrics=None,
                    analyst_notes=opinion.get("reasoning"),
                    analysis_quality=confidence if isinstance(confidence, (int, float)) else 0.5,
                    source_count=0,
                )
                session.add(record)

        except Exception as exc:
            logger.error("실시간 분석 결과 저장 실패 (%s): %s", ticker, exc)

    async def _fetch_recent_news(self, ticker: str) -> list[dict]:
        """DB에서 특정 종목의 최근 뉴스를 조회한다.

        Args:
            ticker: 종목 티커.

        Returns:
            최근 뉴스 목록 (dict 리스트).
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(
                        Article.headline,
                        Article.content,
                        Article.source,
                        Article.published_at,
                        Article.sentiment_score,
                    )
                    .where(Article.tickers_mentioned.contains([ticker]))
                    .order_by(desc(Article.published_at))
                    .limit(_RECENT_NEWS_LIMIT)
                )
                result = await session.execute(stmt)
                rows = result.all()

                return [
                    {
                        "headline": row.headline,
                        "source": row.source,
                        "published_at": row.published_at.isoformat() if row.published_at else None,
                        "sentiment_score": row.sentiment_score,
                    }
                    for row in rows
                ]
        except Exception as exc:
            logger.warning("최근 뉴스 조회 실패 (%s): %s", ticker, exc)
            return []

    async def get_ticker_timeline(
        self, ticker: str, weeks: int = 12
    ) -> list[dict[str, Any]]:
        """종목의 과거 분석 타임라인을 조회한다.

        Args:
            ticker: 종목 티커.
            weeks: 조회할 주 수.

        Returns:
            주간별 분석 결과 목록.
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(HistoricalAnalysis)
                    .where(HistoricalAnalysis.ticker == ticker)
                    .order_by(desc(HistoricalAnalysis.week_start))
                    .limit(weeks)
                )
                result = await session.execute(stmt)
                analyses = result.scalars().all()

                return [
                    {
                        "week_start": a.week_start.isoformat(),
                        "week_end": a.week_end.isoformat(),
                        "sector": a.sector,
                        "timeline_events": a.timeline_events,
                        "market_context": a.market_context,
                        "analyst_notes": a.analyst_notes,
                        "analysis_quality": a.analysis_quality,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in reversed(analyses)
                ]
        except Exception as exc:
            logger.error("종목 타임라인 조회 실패 (%s): %s", ticker, exc)
            return []

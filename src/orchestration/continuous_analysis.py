"""
30분 단위 연속 크롤링 + Opus 분석 모듈.

TradingSystem에서 분리된 run_continuous_crawl_analysis() 함수를 제공한다.
23:00~06:30 KST 사이 매 30분마다 호출되어 delta 크롤링 -> 분류 -> Opus 분석을 수행한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from src.analysis.prompts import build_continuous_analysis_prompt, get_system_prompt
from src.crawler.ai_context_builder import build_ai_context_compact
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.main import TradingSystem

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_ANALYSIS_CACHE_TTL: int = 3600         # 연속 분석 결과 Redis 캐시 TTL (초) — 1시간
_ANALYSIS_HISTORY_MAX: int = 50         # Redis 히스토리 최대 보존 건수
_MAX_HIGH_ISSUES_TELEGRAM: int = 3      # 텔레그램 HIGH 이슈 최대 전송 건수
_MAX_AFFECTED_TICKERS: int = 3          # 이슈당 영향 종목 최대 표시 수
_MAX_RISK_CHARS: int = 100              # 리스크 설명 최대 문자 수
_MAX_NEW_RISKS_TELEGRAM: int = 3        # 텔레그램 NEW 리스크 최대 전송 건수


async def run_continuous_crawl_analysis(ts: TradingSystem) -> dict[str, Any]:
    """30분 단위 연속 크롤링 + Opus 분석을 1회 실행한다.

    23:00~06:30 KST 사이 매 30분마다 호출되어:
    1. 최신 뉴스를 delta 크롤링한다.
    2. Tier 소스(Fear&Greed, 예측시장, Finviz 등)에서 실시간 지표를 수집한다.
    3. Opus가 이전 분석과 비교하여 핵심 이슈 변화를 분석한다.
    4. 분석 결과를 DB에 저장하고 다음 반복에 이전 이슈로 전달한다.

    Args:
        ts: TradingSystem 인스턴스.

    Returns:
        분석 결과 딕셔너리.
    """
    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    now_kst = datetime.now(tz=kst)
    ts._continuous_analysis_iteration += 1
    ts._continuous_analysis_count += 1
    iteration = ts._continuous_analysis_iteration

    # 시간 범위 계산
    if ts._continuous_analysis_last_run is None:
        # 첫 실행: 당일 06:00 KST부터 현재까지
        start_time = now_kst.replace(hour=6, minute=0, second=0, microsecond=0)
        if now_kst.hour < 6:
            start_time -= timedelta(days=1)
        time_range = f"{start_time.strftime('%H:%M')}~{now_kst.strftime('%H:%M')} KST"
    else:
        last_kst = ts._continuous_analysis_last_run.astimezone(kst)
        time_range = f"{last_kst.strftime('%H:%M')}~{now_kst.strftime('%H:%M')} KST"

    logger.info(
        "========== 연속 크롤링 분석 #%d (%s) ==========",
        iteration, time_range,
    )

    results: dict[str, Any] = {"iteration": iteration, "time_range": time_range}

    try:
        # 1. Delta 크롤링 (최신 뉴스 수집)
        logger.info("[연속분석 %d] Delta 크롤링 시작...", iteration)
        crawl_result = await ts.crawl_engine.run(mode="delta")
        new_article_count = crawl_result.get("saved", 0)
        results["crawl"] = {
            "saved": new_article_count,
            "total_raw": crawl_result.get("total_raw", 0),
        }
        logger.info("[연속분석 %d] 새 기사 %d건 수집", iteration, new_article_count)

        # 2. Tier 소스 크롤링 (실시간 지표)
        logger.info("[연속분석 %d] Tier 소스 크롤링...", iteration)
        crawl_context = ""
        try:
            tier_result = await ts.crawl_engine.run(
                mode="full",
                source_keys=[
                    "cnn_fear_greed", "polymarket", "kalshi",
                    "finviz", "investing_com",
                ],
            )
            tier_articles = tier_result.get("articles", [])
            if tier_articles:
                crawl_context = build_ai_context_compact(tier_articles)
            logger.info(
                "[연속분석 %d] Tier 크롤링 완료: %d건",
                iteration, tier_result.get("total_raw", 0),
            )
        except Exception as exc:
            logger.warning("[연속분석 %d] Tier 크롤링 실패: %s", iteration, exc)

        # 3. 새 기사 가져오기 (분류 전 최신 기사)
        new_articles = await ts._fetch_latest_articles(
            limit=max(new_article_count, 30),
        )

        # 4. 뉴스 분류 (Sonnet) + DB 저장
        if new_articles:
            logger.info("[연속분석 %d] 뉴스 분류 (%d건)...", iteration, len(new_articles))
            classified = await ts.classifier.classify_and_store_batch(new_articles)
            results["classified"] = len(classified)
            logger.info("[연속분석 %d] 분류 완료: %d건", iteration, len(classified))

        # 5. 시장 상태 조회
        vix = await ts._fetch_vix()
        regime = await ts._get_current_regime()
        regime_name = regime.get("regime", "sideways")

        # 6. Opus 연속 분석 (핵심)
        logger.info("[연속분석 %d] Opus 핵심 이슈 분석...", iteration)
        analysis_prompt = build_continuous_analysis_prompt(
            new_articles=new_articles,
            previous_issues=ts._continuous_analysis_previous_issues,
            crawl_context=crawl_context,
            regime=regime_name,
            vix=vix,
            iteration=iteration,
            time_range=time_range,
        )

        analysis_result = await ts.claude_client.call_json(
            prompt=analysis_prompt,
            task_type="continuous_analysis",
            system_prompt=get_system_prompt("continuous_analysis"),
            use_cache=False,  # 항상 최신 분석
        )
        results["analysis"] = analysis_result

        # 7. 이전 이슈 업데이트 (다음 반복을 위해)
        if isinstance(analysis_result, dict):
            issues = analysis_result.get("key_issues", [])
            summary = analysis_result.get("summary", "")
            issue_lines = []
            for issue in issues:
                title = issue.get("title", "")
                status = issue.get("status", "")
                impact = issue.get("impact", "")
                desc = issue.get("description", "")
                issue_lines.append(
                    f"- [{impact.upper()}] {title} ({status}): {desc}"
                )
            ts._continuous_analysis_previous_issues = (
                f"[반복 #{iteration} 요약] {summary}\n"
                + "\n".join(issue_lines)
            )

            # 로그에 요약 출력
            sentiment = analysis_result.get("market_sentiment_shift", {})
            logger.info(
                "[연속분석 %d] 완료 | 이슈 %d건 | 센티먼트: %s (신뢰도 %.0f%%) | %s",
                iteration,
                len(issues),
                sentiment.get("direction", "?"),
                sentiment.get("confidence", 0) * 100,
                summary[:100],
            )

        # 8. Redis에 분석 결과 저장 (최신 + 히스토리)
        try:
            result_json = json.dumps(results, ensure_ascii=False, default=str)
            await ts.redis.set(
                "continuous_analysis:latest", result_json, ex=_ANALYSIS_CACHE_TTL,
            )
            await ts.redis.rpush("continuous_analysis:history", result_json)
            # 히스토리는 최대 _ANALYSIS_HISTORY_MAX건만 유지
            await ts.redis.ltrim(
                "continuous_analysis:history", -_ANALYSIS_HISTORY_MAX, -1
            )
        except Exception as exc:
            logger.warning("[연속분석 %d] Redis 저장 실패: %s", iteration, exc)

        # 9. Telegram 알림 (high impact 이슈가 있을 때만)
        if isinstance(analysis_result, dict):
            high_issues = [
                i for i in analysis_result.get("key_issues", [])
                if i.get("impact") == "high"
            ]
            if high_issues and ts.telegram_notifier:
                try:
                    msg_lines = []
                    for hi in high_issues[:_MAX_HIGH_ISSUES_TELEGRAM]:
                        ticker_str = ", ".join(hi.get("affected_tickers", [])[:_MAX_AFFECTED_TICKERS])
                        msg_lines.append(
                            f"- {hi.get('title', '')} [{ticker_str}]\n"
                            f"  {hi.get('description', '')[:100]}"
                        )
                    await ts.telegram_notifier.send_message(
                        title=f"연속분석 #{iteration} - HIGH 이슈 {len(high_issues)}건",
                        message="\n".join(msg_lines),
                        severity="warning",
                    )
                except Exception as exc:
                    logger.debug("연속분석 HIGH 이슈 텔레그램 알림 실패: %s", exc)

            # 새로운 critical 리스크 알림
            new_risks = [
                r for r in analysis_result.get("new_risks", [])
                if r.get("severity") == "critical"
            ]
            if new_risks and ts.telegram_notifier:
                try:
                    risk_msg = "\n".join(
                        f"- {r.get('risk', '')[:_MAX_RISK_CHARS]}"
                        for r in new_risks[:_MAX_NEW_RISKS_TELEGRAM]
                    )
                    await ts.telegram_notifier.send_message(
                        title=f"CRITICAL 리스크 감지 ({len(new_risks)}건)",
                        message=risk_msg,
                        severity="critical",
                    )
                except Exception as exc:
                    logger.debug("CRITICAL 리스크 텔레그램 알림 실패: %s", exc)

        ts._continuous_analysis_last_run = datetime.now(tz=timezone.utc)
        logger.info(
            "========== 연속 크롤링 분석 #%d 완료 ==========", iteration,
        )

    except Exception as exc:
        logger.exception("[연속분석 %d] 실패: %s", iteration, exc)
        results["error"] = str(exc)
        try:
            await ts.alert_manager.send_alert(
                "system",
                f"연속 크롤링 분석 #{iteration} 실패",
                str(exc),
                "warning",
            )
        except Exception as alert_exc:
            logger.debug("연속분석 실패 알림 전송 실패: %s", alert_exc)

    return results

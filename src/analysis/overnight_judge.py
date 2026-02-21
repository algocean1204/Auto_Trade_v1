"""
오버나잇 판단

정규장 마감 전 보유 포지션의 오버나잇 여부를 결정한다.
Claude Opus를 사용하여 고위험 판단을 수행한다.
레짐과 뉴스 신호를 고려하여 리스크 기반 보유/청산을 판단한다.
"""

from __future__ import annotations

from typing import Any

from src.analysis.claude_client import ClaudeClient
from src.analysis.prompts import build_overnight_judgment_prompt, get_system_prompt
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 판단 결과 필수 필드
_REQUIRED_FIELDS = frozenset({"ticker", "decision"})

# 허용 값
_VALID_DECISIONS = frozenset({"hold", "sell"})
_VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})


class OvernightJudge:
    """오버나잇 보유 판단기.

    장 마감 전 각 보유 포지션에 대해 오버나잇 보유 여부를 결정한다.
    Claude Opus를 사용하여 뉴스 신호, 시장 레짐, 리스크 요인을
    종합적으로 고려한 판단을 수행한다.
    """

    def __init__(self, claude_client: ClaudeClient) -> None:
        """OvernightJudge 초기화.

        Args:
            claude_client: Claude API 클라이언트.
        """
        self.client = claude_client
        logger.info("OvernightJudge 초기화 완료")

    async def judge(
        self,
        positions: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        regime: str,
    ) -> list[dict[str, Any]]:
        """각 보유 포지션에 대해 오버나잇 보유 여부를 판단한다.

        Args:
            positions: 현재 보유 포지션 목록.
                각 항목: ``{"ticker", "direction", "quantity", "entry_price",
                          "current_price", "unrealized_pnl", "unrealized_pnl_pct", ...}``
            signals: 장 마감 전후 뉴스/이벤트 신호 목록.
            regime: 현재 시장 레짐 문자열.

        Returns:
            오버나잇 판단 결과 목록. 각 항목:
                - ticker: str
                - decision: "hold" | "sell"
                - sell_ratio: float (1.0이면 전량 청산, 0.5이면 50% 부분 청산)
                - confidence: float (0.0 ~ 1.0)
                - reason: str
                - overnight_risk: "low" | "medium" | "high"
        """
        if not positions:
            logger.info("오버나잇 판단: 보유 포지션 없음")
            return []

        logger.info(
            "오버나잇 판단 시작: 포지션 %d건, 신호 %d건, 레짐=%s",
            len(positions), len(signals), regime,
        )

        # Claude Opus 프롬프트 생성 및 호출
        prompt = build_overnight_judgment_prompt(
            positions=positions,
            signals=signals,
            regime=regime,
        )

        raw_results = await self.client.call_json(
            prompt=prompt,
            task_type="overnight_judgment",
            system_prompt=get_system_prompt("overnight_judgment"),
            max_tokens=4096,
            use_cache=False,  # 장 마감 판단은 캐싱하지 않음
        )

        if not isinstance(raw_results, list):
            logger.warning(
                "Claude 오버나잇 응답이 배열이 아닙니다: %s", type(raw_results),
            )
            raw_results = [raw_results] if isinstance(raw_results, dict) else []

        # 응답 검증
        validated = self._validate_judgments(raw_results, positions)

        # 누락된 포지션에 대해 안전 기본값 적용
        validated = self._fill_missing_positions(validated, positions, regime)

        # 결과 로깅
        hold_count = sum(1 for j in validated if j["decision"] == "hold")
        sell_count = sum(1 for j in validated if j["decision"] == "sell")
        logger.info(
            "오버나잇 판단 완료: 보유 %d건 / 청산 %d건",
            hold_count, sell_count,
        )

        return validated

    def _validate_judgments(
        self,
        judgments: list[Any],
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """오버나잇 판단 결과를 검증하고 정제한다.

        Args:
            judgments: Claude가 반환한 판단 결과 목록.
            positions: 원본 포지션 목록 (티커 교차 검증용).

        Returns:
            검증을 통과한 판단 결과 목록.
        """
        position_tickers: set[str] = {
            str(p.get("ticker", "")).upper() for p in positions
        }

        validated: list[dict[str, Any]] = []
        seen_tickers: set[str] = set()

        for item in judgments:
            if not isinstance(item, dict):
                logger.warning("오버나잇 판단 항목이 딕셔너리가 아닙니다: %s", type(item))
                continue

            # 필수 필드 확인
            missing = _REQUIRED_FIELDS - set(item.keys())
            if missing:
                logger.warning("오버나잇 판단 필수 필드 누락: %s", missing)
                continue

            ticker = str(item["ticker"]).upper()

            # 실제 보유 포지션인지 확인
            if ticker not in position_tickers:
                logger.warning(
                    "오버나잇 판단에 보유하지 않은 종목 포함: %s", ticker,
                )
                continue

            # 중복 방지
            if ticker in seen_tickers:
                logger.warning("오버나잇 판단 중복 종목 무시: %s", ticker)
                continue
            seen_tickers.add(ticker)

            # decision 검증
            decision = str(item.get("decision", "")).lower()
            if decision not in _VALID_DECISIONS:
                logger.warning(
                    "유효하지 않은 오버나잇 판단: %s -> sell로 대체 (안전 우선)",
                    decision,
                )
                decision = "sell"

            # sell_ratio 검증
            try:
                sell_ratio = float(item.get("sell_ratio", 1.0))
            except (ValueError, TypeError):
                sell_ratio = 1.0
            sell_ratio = max(0.0, min(1.0, sell_ratio))
            # hold이면 sell_ratio를 0으로 보정
            if decision == "hold":
                sell_ratio = 0.0

            # confidence 검증
            try:
                confidence = float(item.get("confidence", 0.7))
            except (ValueError, TypeError):
                confidence = 0.7
            confidence = max(0.0, min(1.0, confidence))

            # overnight_risk 검증
            overnight_risk = str(item.get("overnight_risk", "medium")).lower()
            if overnight_risk not in _VALID_RISK_LEVELS:
                overnight_risk = "medium"

            validated.append({
                "ticker": ticker,
                "decision": decision,
                "sell_ratio": round(sell_ratio, 2),
                "confidence": round(confidence, 4),
                "reason": str(item.get("reason", "")),
                "overnight_risk": overnight_risk,
            })

        return validated

    def _fill_missing_positions(
        self,
        validated: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        regime: str,
    ) -> list[dict[str, Any]]:
        """Claude가 판단하지 않은 포지션에 대해 안전 기본값을 적용한다.

        crash/mild_bear 레짐에서는 기본적으로 청산을 권고하고,
        그 외 레짐에서는 보유를 기본값으로 한다.

        Args:
            validated: 검증된 판단 결과 목록.
            positions: 전체 보유 포지션 목록.
            regime: 현재 시장 레짐.

        Returns:
            모든 포지션에 대한 판단이 포함된 목록.
        """
        judged_tickers: set[str] = {j["ticker"] for j in validated}

        bearish_regimes = frozenset({"crash", "mild_bear"})
        regime_str = regime.get("regime", "") if isinstance(regime, dict) else str(regime)
        is_bearish = regime_str in bearish_regimes

        for position in positions:
            ticker = str(position.get("ticker", "")).upper()
            if not ticker or ticker in judged_tickers:
                continue

            if is_bearish:
                default_decision = "sell"
                default_risk = "high"
                default_reason = (
                    f"Claude 응답에서 누락됨. {regime} 레짐이므로 안전을 위해 청산 권고."
                )
                default_sell_ratio = 1.0
            else:
                default_decision = "hold"
                default_risk = "medium"
                default_reason = "Claude 응답에서 누락됨. 기본 보유 유지."
                default_sell_ratio = 0.0

            logger.warning(
                "오버나잇 판단 누락 포지션 기본값 적용: %s -> %s (%s 레짐)",
                ticker, default_decision, regime,
            )

            validated.append({
                "ticker": ticker,
                "decision": default_decision,
                "sell_ratio": default_sell_ratio,
                "confidence": 0.5,
                "reason": default_reason,
                "overnight_risk": default_risk,
            })

        return validated

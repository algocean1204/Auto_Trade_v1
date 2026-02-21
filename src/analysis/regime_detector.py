"""
시장 레짐 감지기

VIX + 뉴스 종합으로 현재 시장 상태를 판단한다.
VIX 기반 1차 분류 후 Claude Opus로 종합 판단을 수행한다.
레짐 변경 시 로깅 및 알림을 생성한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.analysis.claude_client import ClaudeClient
from src.analysis.prompts import build_regime_detection_prompt, get_system_prompt
from src.utils.logger import get_logger

logger = get_logger(__name__)

# VIX 기반 레짐 분류 기준
_REGIME_VIX_RANGES: dict[str, tuple[float, float]] = {
    "strong_bull": (0.0, 15.0),
    "mild_bull": (15.0, 20.0),
    "sideways": (20.0, 25.0),
    "mild_bear": (25.0, 35.0),
    "crash": (35.0, float("inf")),
}

# 유효 레짐 값
_VALID_REGIMES = frozenset(_REGIME_VIX_RANGES.keys())

# 기본 저장 경로
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DEFAULT_REGIME_FILE = _DATA_DIR / "regime.json"

# 레짐 감지 실패 시 기본 노출 비율 (%)
_DEFAULT_EXPOSURE: float = 50.0


class RegimeDetector:
    """시장 레짐 감지기.

    VIX 지수와 뉴스 신호, 시장 데이터를 종합하여
    현재 시장 상태(레짐)를 판단한다.
    VIX 기반 1차 분류를 수행한 후 Claude Opus로 종합 판단을 요청한다.
    레짐 변경 시 이전 레짐과 비교하여 변경 로그를 생성한다.
    """

    def __init__(self, claude_client: ClaudeClient) -> None:
        """RegimeDetector 초기화.

        Args:
            claude_client: Claude API 클라이언트.
        """
        self.client = claude_client
        self.current_regime: str | None = None
        self.last_updated: datetime | None = None
        logger.info("RegimeDetector 초기화 완료")

    async def detect(
        self,
        vix: float,
        market_data: dict[str, Any],
        recent_signals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """시장 레짐을 판단한다.

        1. VIX 기반 1차 레짐 분류
        2. Claude Opus로 종합 판단 (VIX + 뉴스 + 시장 데이터)
        3. 레짐 변경 시 로깅

        Args:
            vix: 현재 VIX 지수.
            market_data: 주요 시장 데이터 딕셔너리.
                예: ``{"sp500_change_pct", "nasdaq_change_pct", "treasury_10y", ...}``
            recent_signals: 최근 분류된 뉴스 신호 목록.

        Returns:
            레짐 판단 결과:
                - regime: str -- 시장 레짐 이름
                - vix: float -- 현재 VIX 값
                - vix_based_regime: str -- VIX만으로 판단한 레짐
                - confidence: float (0.0 ~ 1.0)
                - vix_assessment: str
                - trend_assessment: str
                - macro_assessment: str
                - risk_factors: list[str]
                - recommended_exposure_pct: float
                - previous_regime: str | None
                - regime_changed: bool
        """
        logger.info("레짐 감지 시작: VIX=%.2f", vix)

        # 1. VIX 기반 1차 분류
        vix_regime = self.get_vix_based_regime(vix)
        logger.info("VIX 기반 1차 분류: %s (VIX=%.2f)", vix_regime, vix)

        # 2. Claude Opus 종합 판단
        prompt = build_regime_detection_prompt(
            vix=vix,
            market_data=market_data,
            recent_signals=recent_signals,
        )

        raw_result = await self.client.call_json(
            prompt=prompt,
            task_type="regime_detection",
            system_prompt=get_system_prompt("regime_detection"),
            max_tokens=4096,
            use_cache=False,  # 레짐 판단은 항상 최신 데이터 기반
        )

        if not isinstance(raw_result, dict):
            logger.warning(
                "Claude 레짐 응답이 딕셔너리가 아닙니다. VIX 기반 결과를 사용합니다."
            )
            raw_result = {}

        # Claude 판단 레짐 추출 및 검증
        claude_regime = str(raw_result.get("regime", vix_regime)).lower()
        if claude_regime not in _VALID_REGIMES:
            logger.warning(
                "Claude가 유효하지 않은 레짐을 반환: %s, VIX 기반(%s)으로 대체",
                claude_regime, vix_regime,
            )
            claude_regime = vix_regime

        # confidence 검증
        try:
            confidence = float(raw_result.get("confidence", 0.7))
        except (ValueError, TypeError):
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))

        # recommended_exposure_pct 검증
        try:
            recommended_exposure = float(raw_result.get("recommended_exposure_pct", _DEFAULT_EXPOSURE))
        except (ValueError, TypeError):
            recommended_exposure = _DEFAULT_EXPOSURE
        recommended_exposure = max(0.0, min(100.0, recommended_exposure))

        # risk_factors 검증
        risk_factors = raw_result.get("risk_factors", [])
        if not isinstance(risk_factors, list):
            risk_factors = []
        risk_factors = [str(rf) for rf in risk_factors]

        # 3. 레짐 변경 감지
        previous_regime = self.current_regime
        regime_changed = (
            previous_regime is not None and previous_regime != claude_regime
        )

        if regime_changed:
            logger.warning(
                "시장 레짐 변경 감지: %s -> %s (VIX=%.2f, confidence=%.2f)",
                previous_regime, claude_regime, vix, confidence,
            )
        else:
            logger.info(
                "시장 레짐 유지: %s (VIX=%.2f, confidence=%.2f)",
                claude_regime, vix, confidence,
            )

        # 상태 업데이트
        self.current_regime = claude_regime
        self.last_updated = datetime.now(timezone.utc)

        return {
            "regime": claude_regime,
            "vix": vix,
            "vix_based_regime": vix_regime,
            "confidence": round(confidence, 4),
            "vix_assessment": str(raw_result.get("vix_assessment", "")),
            "trend_assessment": str(raw_result.get("trend_assessment", "")),
            "macro_assessment": str(raw_result.get("macro_assessment", "")),
            "risk_factors": risk_factors,
            "recommended_exposure_pct": round(recommended_exposure, 2),
            "previous_regime": previous_regime,
            "regime_changed": regime_changed,
        }

    def get_vix_based_regime(self, vix: float) -> str:
        """VIX 값만으로 1차 레짐을 분류한다.

        Args:
            vix: 현재 VIX 지수.

        Returns:
            레짐 이름 문자열.
        """
        for regime_name, (low, high) in _REGIME_VIX_RANGES.items():
            if low <= vix < high:
                return regime_name

        # VIX가 음수이거나 예외적인 경우 crash로 처리
        logger.warning("VIX 값이 정의된 범위 밖: %.2f, crash로 분류", vix)
        return "crash"

    @staticmethod
    def save_regime(
        regime_result: dict[str, Any],
        path: Path | str | None = None,
    ) -> None:
        """레짐 판단 결과를 JSON 파일로 저장한다.

        스케줄러 플로우에서 regime.json에 결과를 영속화할 때 사용한다.

        Args:
            regime_result: detect() 반환값.
            path: 저장 경로. None이면 data/regime.json 사용.
        """
        target = Path(path) if path else _DEFAULT_REGIME_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        # datetime 직렬화를 위해 문자열 변환
        serializable = dict(regime_result)
        for key in ("last_updated",):
            if key in serializable and isinstance(serializable[key], datetime):
                serializable[key] = serializable[key].isoformat()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info("레짐 저장 완료: %s (regime=%s)", target, regime_result.get("regime"))

    @staticmethod
    def load_regime(
        path: Path | str | None = None,
    ) -> dict[str, Any] | None:
        """이전에 저장된 레짐 판단 결과를 로드한다.

        Args:
            path: 파일 경로. None이면 data/regime.json 사용.

        Returns:
            레짐 결과 딕셔너리. 파일이 없으면 None.
        """
        target = Path(path) if path else _DEFAULT_REGIME_FILE
        if not target.exists():
            logger.info("저장된 레짐 없음: %s", target)
            return None
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                logger.info("레짐 로드 완료: %s (regime=%s)", target, data.get("regime"))
                return data
            logger.warning("레짐 파일 형식 오류: 딕셔너리가 아닙니다.")
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("레짐 로드 실패: %s", exc)
            return None

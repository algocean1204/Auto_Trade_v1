"""전략 파라미터 관리

strategy_params.json 파일로 영속화하며,
피드백 루프에서 조정 가능 (사용자 승인 필요).
VIX 기반 시장 레짐별 전략 및 안전 한도를 관리한다.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 기본 청산 파라미터
# ---------------------------------------------------------------------------
TAKE_PROFIT_PCT: float = 3.0        # 기초자산 ~1.5% 움직임
TRAILING_STOP_PCT: float = 1.5      # 최고점 대비
STOP_LOSS_PCT: float = -2.0         # 2X이므로 빠른 손절
EOD_CLOSE: bool = True              # 정규장 마감 30분 전 청산

# ---------------------------------------------------------------------------
# 보유 기간 관리
# ---------------------------------------------------------------------------
HOLDING_RULES: dict[int, str] = {
    0: "당일 청산 목표 (기본)",
    1: "추세 지속 시에만 보유, 아니면 청산",
    2: "강한 근거 없으면 청산",
    3: "경고 + 50% 부분 청산",
    4: "75% 청산",
    5: "즉시 100% 청산",
}

# ---------------------------------------------------------------------------
# VIX 기반 시장 레짐별 전략
# ---------------------------------------------------------------------------
REGIMES: dict[str, dict[str, Any]] = {
    "strong_bull": {"vix_range": (0, 15), "take_profit": 4.0, "max_hold_days": 3},
    "mild_bull": {"vix_range": (15, 20), "take_profit": 3.0, "max_hold_days": 2},
    "sideways": {"vix_range": (20, 25), "take_profit": 2.0, "max_hold_days": 0},
    "mild_bear": {"vix_range": (25, 30), "strategy": "inverse_2x"},
    "crash": {"vix_range": (30, 100), "strategy": "no_new_buy"},
}

# ---------------------------------------------------------------------------
# 안전 한도
# ---------------------------------------------------------------------------
MIN_CONFIDENCE: float = 0.7
MAX_POSITION_PCT: float = 15.0
MAX_TOTAL_POSITION_PCT: float = 80.0
MAX_DAILY_TRADES: int = 30
MAX_DAILY_LOSS_PCT: float = -5.0
MAX_HOLD_DAYS: int = 5
VIX_SHUTDOWN_THRESHOLD: int = 35

# ---------------------------------------------------------------------------
# 기본 파라미터 (JSON 영속화 대상)
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, Any] = {
    "take_profit_pct": TAKE_PROFIT_PCT,
    "trailing_stop_pct": TRAILING_STOP_PCT,
    "stop_loss_pct": STOP_LOSS_PCT,
    "eod_close": EOD_CLOSE,
    "min_confidence": MIN_CONFIDENCE,
    "max_position_pct": MAX_POSITION_PCT,
    "max_total_position_pct": MAX_TOTAL_POSITION_PCT,
    "max_daily_trades": MAX_DAILY_TRADES,
    "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
    "max_hold_days": MAX_HOLD_DAYS,
    "vix_shutdown_threshold": VIX_SHUTDOWN_THRESHOLD,
}

# 파라미터별 허용 조정 범위 (비율 기반 검증용)
_ADJUSTMENT_LIMITS: dict[str, float] = {
    "take_profit_pct": 0.10,
    "trailing_stop_pct": 0.10,
    "stop_loss_pct": 0.10,
    "min_confidence": 0.10,
    "max_position_pct": 0.10,
    "max_total_position_pct": 0.10,
    "max_daily_trades": 0.10,
    "max_daily_loss_pct": 0.10,
    "max_hold_days": 0.10,
    "vix_shutdown_threshold": 0.10,
}


class StrategyParams:
    """전략 파라미터 관리 클래스.

    strategy_params.json에서 파라미터를 로드하고 저장한다.
    피드백 루프 등에서 파라미터를 조정할 때 10% 이내 변경만 허용한다.
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        """StrategyParams 초기화.

        Args:
            config_path: strategy_params.json 경로.
                         None이면 프로젝트 루트의 strategy_params.json 사용.
        """
        if config_path is None:
            self._config_path = Path(__file__).resolve().parents[2] / "strategy_params.json"
        else:
            self._config_path = Path(config_path)

        self._params: dict[str, Any] = dict(_DEFAULTS)
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_param(self, name: str) -> Any:
        """파라미터 값 조회.

        Args:
            name: 파라미터 키 이름.

        Returns:
            파라미터 값.

        Raises:
            KeyError: 존재하지 않는 파라미터 이름.
        """
        if name not in self._params:
            raise KeyError(f"Unknown parameter: {name}")
        return self._params[name]

    def set_param(self, name: str, value: Any) -> None:
        """파라미터 값 설정 후 파일에 저장.

        Args:
            name: 파라미터 키 이름.
            value: 새 값.

        Raises:
            KeyError: 존재하지 않는 파라미터 이름.
        """
        if name not in self._params:
            raise KeyError(f"Unknown parameter: {name}")
        old_value = self._params[name]
        self._params[name] = value
        logger.info("Parameter '%s' changed: %s -> %s", name, old_value, value)
        self._save()

    def get_regime_config(self, vix_value: float) -> dict[str, Any]:
        """현재 VIX 값에 맞는 시장 레짐 설정 반환.

        Args:
            vix_value: 현재 VIX 지수 값.

        Returns:
            레짐 이름과 설정을 담은 딕셔너리.
            매칭되는 레짐이 없으면 crash 레짐 반환.
        """
        for regime_name, config in REGIMES.items():
            low, high = config["vix_range"]
            if low <= vix_value < high:
                logger.debug("VIX %.1f -> regime '%s'", vix_value, regime_name)
                return {"regime": regime_name, **config}

        logger.warning("VIX %.1f out of defined ranges, defaulting to crash", vix_value)
        return {"regime": "crash", **REGIMES["crash"]}

    def validate_adjustment(
        self, param: str, old_val: float, new_val: float
    ) -> bool:
        """파라미터 조정이 허용 범위(10%) 이내인지 검증.

        Args:
            param: 파라미터 키 이름.
            old_val: 기존 값.
            new_val: 새 값.

        Returns:
            True이면 허용 범위 이내.
        """
        limit = _ADJUSTMENT_LIMITS.get(param)
        if limit is None:
            logger.warning("No adjustment limit defined for '%s', rejecting", param)
            return False

        if old_val == 0:
            allowed = abs(new_val) <= limit
        else:
            change_ratio = abs((new_val - old_val) / old_val)
            allowed = change_ratio <= limit

        if not allowed:
            logger.warning(
                "Adjustment rejected for '%s': %.4f -> %.4f (limit: %.0f%%)",
                param, old_val, new_val, limit * 100,
            )
        return allowed

    def get_holding_rule(self, days_held: int) -> str:
        """보유 일수에 따른 규칙 반환.

        Args:
            days_held: 현재 보유 일수.

        Returns:
            보유 규칙 설명 문자열.
        """
        if days_held in HOLDING_RULES:
            return HOLDING_RULES[days_held]
        return HOLDING_RULES[5]  # 5일 이상이면 즉시 100% 청산

    def to_dict(self) -> dict[str, Any]:
        """현재 파라미터를 딕셔너리로 반환."""
        return dict(self._params)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """strategy_params.json에서 파라미터 로드."""
        if not self._config_path.exists():
            logger.info(
                "Config file not found at %s, using defaults", self._config_path
            )
            self._save()
            return

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in self._params:
                if key in data:
                    self._params[key] = data[key]
            logger.info("Loaded strategy params from %s", self._config_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load config: %s, using defaults", e)

    def _save(self) -> None:
        """현재 파라미터를 strategy_params.json에 저장."""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._params, f, indent=2, ensure_ascii=False)
                f.write("\n")
            logger.debug("Saved strategy params to %s", self._config_path)
        except OSError as e:
            logger.error("Failed to save config: %s", e)

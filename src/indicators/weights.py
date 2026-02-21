"""
기술적 지표 가중치 관리 모듈

- 기본 가중치 (Thinking.md 기준)
- 사용자 커스텀 가중치 (Flutter 슬라이더 연동)
- Redis 캐시 + DB 저장/로드
- 프리셋 관리
"""

import json
from typing import Any

from src.db.connection import get_redis, get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Redis 키 접두사
_REDIS_KEY_WEIGHTS = "indicator:weights"
_REDIS_KEY_ENABLED = "indicator:enabled"
_REDIS_KEY_PRESETS = "indicator:presets"


class WeightsManager:
    """기술적 지표 가중치 관리 클래스.

    Redis에 가중치를 캐시하고, DB에 영구 저장한다.
    """

    DEFAULT_WEIGHTS: dict[str, int] = {
        "rsi_7": 10,        # 단기 RSI
        "rsi_14": 15,       # 표준 RSI
        "rsi_21": 10,       # 중기 RSI
        "macd": 20,
        "stochastic": 10,   # 15에서 축소
        "ma_cross": 20,
        "adx": 5,           # 10에서 축소
        "bollinger": 10,
        "atr": 0,
        "volume_ratio": 0,
        "obv": 0,
    }  # Total: 100

    PRESETS: dict[str, dict[str, int]] = {
        "default": {
            "rsi_7": 10, "rsi_14": 15, "rsi_21": 10,
            "macd": 20, "stochastic": 10, "ma_cross": 20,
            "adx": 5, "bollinger": 10, "atr": 0, "volume_ratio": 0, "obv": 0,
        },
        "momentum_heavy": {
            "rsi_7": 15, "rsi_14": 20, "rsi_21": 15,
            "macd": 25, "stochastic": 15, "ma_cross": 5,
            "adx": 5, "bollinger": 0, "atr": 0, "volume_ratio": 0, "obv": 0,
        },
        "trend_following": {
            "rsi_7": 5, "rsi_14": 10, "rsi_21": 5,
            "macd": 15, "stochastic": 5, "ma_cross": 35,
            "adx": 20, "bollinger": 5, "atr": 0, "volume_ratio": 0, "obv": 0,
        },
        "volatility_focus": {
            "rsi_7": 5, "rsi_14": 15, "rsi_21": 5,
            "macd": 10, "stochastic": 10, "ma_cross": 10,
            "adx": 5, "bollinger": 35, "atr": 5, "volume_ratio": 0, "obv": 0,
        },
        "rsi_focused": {
            "rsi_7": 20, "rsi_14": 25, "rsi_21": 20,
            "macd": 15, "stochastic": 5, "ma_cross": 10,
            "adx": 5, "bollinger": 0, "atr": 0, "volume_ratio": 0, "obv": 0,
        },
    }

    async def get_weights(self) -> dict[str, int]:
        """현재 적용 중인 가중치를 반환한다.

        Redis 캐시를 우선 조회하고, 없으면 기본 가중치를 반환한다.

        Returns:
            지표별 가중치 딕셔너리.
        """
        try:
            redis = get_redis()
            cached = await redis.get(_REDIS_KEY_WEIGHTS)
            if cached:
                weights = json.loads(cached)
                logger.debug("Redis에서 가중치 로드 완료")
                return weights
        except Exception as e:
            logger.warning("Redis 가중치 조회 실패, 기본값 사용: %s", e)

        return dict(self.DEFAULT_WEIGHTS)

    async def set_weights(self, weights: dict[str, int]) -> None:
        """가중치를 설정하고 저장한다.

        Args:
            weights: 지표별 가중치 딕셔너리. 합계는 100이어야 한다.

        Raises:
            ValueError: 알 수 없는 지표가 포함되거나 합계가 100이 아닌 경우.
        """
        # 유효성 검증
        valid_indicators = set(self.DEFAULT_WEIGHTS.keys())
        unknown = set(weights.keys()) - valid_indicators
        if unknown:
            raise ValueError(f"알 수 없는 지표: {unknown}")

        for name, w in weights.items():
            if not isinstance(w, (int, float)) or w < 0:
                raise ValueError(f"가중치는 0 이상이어야 합니다: {name}={w}")

        total = sum(weights.values())
        if total != 100:
            raise ValueError(f"가중치 합계는 100이어야 합니다 (현재: {total})")

        # 완전한 가중치 딕셔너리 구성 (누락된 지표는 0으로)
        full_weights = dict(self.DEFAULT_WEIGHTS)
        for k, v in weights.items():
            full_weights[k] = int(v)

        try:
            redis = get_redis()
            await redis.set(_REDIS_KEY_WEIGHTS, json.dumps(full_weights))
            logger.info("가중치 저장 완료: %s", full_weights)
        except Exception as e:
            logger.error("Redis 가중치 저장 실패: %s", e)
            raise

    async def get_enabled(self) -> dict[str, bool]:
        """각 지표의 활성화 상태를 반환한다.

        Returns:
            지표별 활성화 여부 딕셔너리.
        """
        # 기본값: 가중치 > 0인 지표만 활성화
        default_enabled = {
            name: weight > 0 for name, weight in self.DEFAULT_WEIGHTS.items()
        }

        try:
            redis = get_redis()
            cached = await redis.get(_REDIS_KEY_ENABLED)
            if cached:
                enabled = json.loads(cached)
                # 새로 추가된 지표가 있을 수 있으므로 default와 병합
                merged = dict(default_enabled)
                merged.update(enabled)
                return merged
        except Exception as e:
            logger.warning("Redis 활성화 상태 조회 실패, 기본값 사용: %s", e)

        return default_enabled

    async def set_enabled(self, indicator: str, enabled: bool) -> None:
        """특정 지표의 활성화 상태를 변경한다.

        Args:
            indicator: 지표 이름.
            enabled: 활성화 여부.

        Raises:
            ValueError: 알 수 없는 지표인 경우.
        """
        if indicator not in self.DEFAULT_WEIGHTS:
            raise ValueError(f"알 수 없는 지표: {indicator}")

        current = await self.get_enabled()
        current[indicator] = enabled

        try:
            redis = get_redis()
            await redis.set(_REDIS_KEY_ENABLED, json.dumps(current))
            logger.info("지표 활성화 변경: %s = %s", indicator, enabled)
        except Exception as e:
            logger.error("Redis 활성화 상태 저장 실패: %s", e)
            raise

    async def apply_preset(self, preset_name: str) -> dict[str, int]:
        """프리셋을 적용한다.

        Args:
            preset_name: 프리셋 이름.

        Returns:
            적용된 가중치 딕셔너리.

        Raises:
            ValueError: 존재하지 않는 프리셋인 경우.
        """
        # 내장 프리셋 확인
        if preset_name in self.PRESETS:
            weights = dict(self.PRESETS[preset_name])
        else:
            # 사용자 커스텀 프리셋 확인
            custom_presets = await self._load_custom_presets()
            if preset_name not in custom_presets:
                available = list(self.PRESETS.keys()) + list(custom_presets.keys())
                raise ValueError(
                    f"프리셋 '{preset_name}'이 없습니다. 사용 가능: {available}"
                )
            weights = custom_presets[preset_name]

        await self.set_weights(weights)
        logger.info("프리셋 적용 완료: %s", preset_name)
        return weights

    async def save_as_preset(self, name: str, weights: dict[str, int]) -> None:
        """현재 가중치를 새 프리셋으로 저장한다.

        Args:
            name: 프리셋 이름.
            weights: 저장할 가중치.

        Raises:
            ValueError: 내장 프리셋 이름과 충돌하는 경우.
        """
        if name in self.PRESETS:
            raise ValueError(
                f"'{name}'은 내장 프리셋과 이름이 충돌합니다. 다른 이름을 사용하세요."
            )

        custom_presets = await self._load_custom_presets()
        custom_presets[name] = dict(weights)

        try:
            redis = get_redis()
            await redis.set(_REDIS_KEY_PRESETS, json.dumps(custom_presets))
            logger.info("커스텀 프리셋 저장 완료: %s", name)
        except Exception as e:
            logger.error("커스텀 프리셋 저장 실패: %s", e)
            raise

    async def list_presets(self) -> dict[str, dict[str, int]]:
        """모든 프리셋(내장 + 커스텀)을 반환한다.

        Returns:
            프리셋명 -> 가중치 딕셔너리의 딕셔너리.
        """
        all_presets = dict(self.PRESETS)
        custom = await self._load_custom_presets()
        all_presets.update(custom)
        return all_presets

    async def _load_custom_presets(self) -> dict[str, dict[str, int]]:
        """Redis에서 커스텀 프리셋을 로드한다."""
        try:
            redis = get_redis()
            cached = await redis.get(_REDIS_KEY_PRESETS)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning("커스텀 프리셋 로드 실패: %s", e)
        return {}

"""F8 ML -- 주간 자동 학습 파이프라인이다."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from src.common.database_gateway import SessionFactory
from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.optimization.models import (
    DateRange,
    TrainingReport,
)

logger = get_logger(__name__)

# 학습 기간: 최근 4주이다
_TRAINING_WEEKS: int = 4

# 배포 기준 AUC이다
_DEPLOY_THRESHOLD: float = 0.65


def _build_date_range() -> DateRange:
    """최근 4주 기간을 생성한다."""
    end = datetime.now()
    start = end - timedelta(weeks=_TRAINING_WEEKS)
    return DateRange(start=start, end=end)


async def _run_prepare(
    date_range: DateRange,
    session_factory: SessionFactory,
    cache: CacheClient | None,
) -> object:
    """데이터 준비 단계를 실행한다."""
    from src.optimization.ml.data_preparer import prepare_data
    return await prepare_data(date_range, session_factory, cache)


def _run_engineer(prepared: object) -> object:
    """피처 엔지니어링 단계를 실행한다."""
    from src.optimization.ml.feature_engineer import engineer_features
    return engineer_features(prepared)


def _run_target(prepared: object) -> object:
    """타겟 생성 단계를 실행한다."""
    from src.optimization.ml.target_builder import build_targets
    return build_targets(prepared)


def _run_train(features: object, labels: object) -> object:
    """모델 학습 단계를 실행한다."""
    from src.optimization.ml.lgbm_trainer import train_model
    return train_model(features, labels)


def _run_optimize(features: object, labels: object) -> object:
    """하이퍼파라미터 최적화 단계를 실행한다."""
    from src.optimization.ml.optuna_optimizer import optimize_params
    return optimize_params(features.features, labels.labels)


def _run_walk_forward(prepared: object, optimized: object) -> object:
    """Walk-Forward 검증 단계를 실행한다."""
    from src.optimization.ml.walk_forward import walk_forward_validate
    return walk_forward_validate(prepared, optimized)


def _should_deploy(avg_score: float) -> bool:
    """배포 여부를 판단한다. AUC가 임계값 이상이면 배포한다."""
    return avg_score >= _DEPLOY_THRESHOLD


async def run_auto_training(
    session_factory: SessionFactory,
    cache: CacheClient | None = None,
) -> TrainingReport:
    """주간 자동 학습 파이프라인을 실행한다.

    순서: prepare -> engineer -> target -> train -> optimize -> walk_forward.
    AUC가 0.65 이상이면 모델을 배포 상태로 표시한다.
    """
    logger.info("=== 주간 자동 학습 시작 ===")

    # 1. 데이터 준비이다
    date_range = _build_date_range()
    prepared = await _run_prepare(date_range, session_factory, cache)
    logger.info("데이터 준비 완료: %d행", prepared.row_count)

    # 2. 피처 엔지니어링이다 (CPU 집약 → 별도 스레드)
    features = await asyncio.to_thread(_run_engineer, prepared)

    # 3. 타겟 생성이다
    labels = await asyncio.to_thread(_run_target, prepared)

    # 4. 모델 학습이다 (LightGBM 5-fold → 별도 스레드, 이벤트루프 비차단)
    trained = await asyncio.to_thread(_run_train, features, labels)

    # 5. 하이퍼파라미터 최적화이다 (Optuna 200 trials → 별도 스레드)
    optimized = await asyncio.to_thread(_run_optimize, features, labels)

    # 6. Walk-Forward 검증이다 (다중 fold → 별도 스레드)
    wf_result = await asyncio.to_thread(_run_walk_forward, prepared, optimized)

    # 배포 판단이다
    deployed = _should_deploy(wf_result.avg_score)
    version = datetime.now().strftime("v%Y%m%d_%H%M%S")

    metrics = {
        "training_auc": trained.metrics.get("avg_auc", 0.0),
        "optimized_auc": optimized.best_score,
        "walk_forward_auc": wf_result.avg_score,
        "stability": wf_result.stability,
        "folds": wf_result.folds,
    }

    logger.info(
        "학습 완료: version=%s, deployed=%s, wf_auc=%.4f",
        version, deployed, wf_result.avg_score,
    )

    return TrainingReport(
        model_version=version,
        metrics=metrics,
        deployed=deployed,
    )

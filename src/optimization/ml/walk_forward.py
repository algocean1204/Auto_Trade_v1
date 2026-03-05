"""F8 ML -- 4주 train / 1주 test Walk-Forward 검증이다."""

from __future__ import annotations

import math

from src.common.logger import get_logger
from src.optimization.models import OptimizedParams, PreparedData, WalkForwardResult

logger = get_logger(__name__)

# 4주 학습 / 1주 테스트 (분봉 기준 근사치)이다
_TRAIN_DAYS: int = 20
_TEST_DAYS: int = 5
_MINUTES_PER_DAY: int = 390  # 6.5시간 정규장


def _calculate_fold_count(total_rows: int) -> int:
    """데이터 크기에서 가능한 fold 수를 계산한다."""
    window = (_TRAIN_DAYS + _TEST_DAYS) * _MINUTES_PER_DAY
    if window <= 0 or total_rows < window:
        return 1
    return max(1, (total_rows - _TRAIN_DAYS * _MINUTES_PER_DAY) // (_TEST_DAYS * _MINUTES_PER_DAY))


def _evaluate_fold(
    train_data: list[dict],
    test_data: list[dict],
    params: dict,
) -> float:
    """단일 fold에서 AUC를 계산한다."""
    try:
        import lightgbm as lgb
        import numpy as np
        from sklearn.metrics import roc_auc_score
    except ImportError as exc:
        logger.error("lightgbm/sklearn 미설치: %s", exc)
        return 0.5

    from src.optimization.ml.feature_engineer import engineer_features
    from src.optimization.ml.target_builder import build_targets
    from src.optimization.models import PreparedData as PD

    # train/test 각각 피처/라벨 생성이다
    train_pd = PD(data=train_data, row_count=len(train_data), date_range="")
    test_pd = PD(data=test_data, row_count=len(test_data), date_range="")

    train_fm = engineer_features(train_pd)
    test_fm = engineer_features(test_pd)
    train_lv = build_targets(train_pd)
    test_lv = build_targets(test_pd)

    if not train_fm.features or not test_fm.features:
        return 0.5

    x_train = np.array(train_fm.features)
    y_train = np.array(train_lv.labels)
    x_test = np.array(test_fm.features)
    y_test = np.array(test_lv.labels)

    lgb_params = {
        "objective": "binary", "metric": "auc",
        "verbose": -1, **params,
    }
    dtrain = lgb.Dataset(x_train, label=y_train)
    model = lgb.train(lgb_params, dtrain, num_boost_round=200)

    preds = model.predict(x_test)

    # 라벨이 단일 클래스면 AUC 계산 불가이다
    if len(set(y_test)) < 2:
        return 0.5

    return float(roc_auc_score(y_test, preds))


def _compute_stability(scores: list[float]) -> float:
    """fold 점수의 안정성을 계산한다 (1 - CV)."""
    if len(scores) < 2:
        return 1.0
    mean = sum(scores) / len(scores)
    if mean == 0:
        return 0.0
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    cv = math.sqrt(variance) / mean
    return max(0.0, 1.0 - cv)


def walk_forward_validate(
    prepared: PreparedData, optimized: OptimizedParams,
) -> WalkForwardResult:
    """Walk-Forward 방식으로 모델 성능을 검증한다.

    4주 학습 / 1주 테스트 윈도우를 슬라이딩하며,
    각 fold의 AUC와 전체 안정성을 측정한다.
    """
    data = prepared.data
    fold_count = _calculate_fold_count(len(data))

    logger.info("Walk-Forward 시작: %d folds, 데이터 %d행", fold_count, len(data))

    train_size = _TRAIN_DAYS * _MINUTES_PER_DAY
    test_size = _TEST_DAYS * _MINUTES_PER_DAY
    fold_scores: list[float] = []

    for i in range(fold_count):
        start = i * test_size
        train_end = start + train_size
        test_end = train_end + test_size

        if test_end > len(data):
            break

        train_slice = data[start:train_end]
        test_slice = data[train_end:test_end]

        score = _evaluate_fold(train_slice, test_slice, optimized.best_params)
        fold_scores.append(score)
        logger.info("Fold %d/%d: AUC=%.4f", i + 1, fold_count, score)

    if not fold_scores:
        fold_scores = [0.5]

    avg = sum(fold_scores) / len(fold_scores)
    stability = _compute_stability(fold_scores)

    logger.info(
        "Walk-Forward 완료: avg_auc=%.4f, stability=%.4f", avg, stability,
    )

    return WalkForwardResult(
        folds=len(fold_scores),
        avg_score=avg,
        stability=stability,
        fold_scores=fold_scores,
    )

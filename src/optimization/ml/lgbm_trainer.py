"""F8 ML -- LightGBM TimeSeriesSplit 학습이다."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from src.common.logger import get_logger
from src.common.paths import get_data_dir
from src.optimization.models import FeatureMatrix, LabelVector, TrainedModel

logger = get_logger(__name__)


def _get_model_dir() -> Path:
    """모델 저장 디렉토리를 반환한다. data/models/ 하위이다."""
    return get_data_dir() / "models"

# 기본 LightGBM 하이퍼파라미터이다
_DEFAULT_PARAMS: dict = {
    "objective": "binary",
    "metric": "auc",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
}

_N_SPLITS: int = 5
_NUM_BOOST_ROUND: int = 200


def _ensure_model_dir() -> Path:
    """모델 저장 디렉토리를 생성한다."""
    model_dir = _get_model_dir()
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def _train_with_cv(
    features: list[list[float]],
    labels: list[int],
    feature_names: list[str],
    params: dict | None = None,
) -> tuple[object, dict]:
    """LightGBM을 TimeSeriesSplit으로 학습한다."""
    try:
        import lightgbm as lgb
        import numpy as np
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import roc_auc_score
    except ImportError as exc:
        logger.error("LightGBM/sklearn 미설치: %s", exc)
        raise ImportError(
            "lightgbm, scikit-learn 설치가 필요하다: "
            "pip install lightgbm scikit-learn"
        ) from exc

    x_arr = np.array(features)
    y_arr = np.array(labels)
    train_params = {**_DEFAULT_PARAMS, **(params or {})}

    tscv = TimeSeriesSplit(n_splits=_N_SPLITS)
    fold_scores: list[float] = []
    best_model: object = None

    for train_idx, val_idx in tscv.split(x_arr):
        x_train, x_val = x_arr[train_idx], x_arr[val_idx]
        y_train, y_val = y_arr[train_idx], y_arr[val_idx]

        dtrain = lgb.Dataset(x_train, label=y_train, feature_name=feature_names)
        dval = lgb.Dataset(x_val, label=y_val, reference=dtrain)

        model = lgb.train(
            train_params, dtrain,
            num_boost_round=_NUM_BOOST_ROUND,
            valid_sets=[dval],
        )

        preds = model.predict(x_val)
        # 검증 세트가 단일 클래스만 포함하면 AUC 계산이 불가능하다
        if len(set(y_val)) < 2:
            logger.warning("Fold 검증 세트 단일 클래스 — AUC=0.5로 대체한다")
            score = 0.5
        else:
            score = roc_auc_score(y_val, preds)
        fold_scores.append(score)
        best_model = model

    # 데이터 부족으로 fold가 하나도 생성되지 않은 경우 빈 결과를 반환한다
    if best_model is None:
        logger.warning("TimeSeriesSplit fold 없음 — 데이터가 부족하다")
        metrics = {"avg_auc": 0.0, "std_auc": 0.0, "fold_scores": []}
        return None, metrics

    metrics = {
        "avg_auc": float(np.mean(fold_scores)),
        "std_auc": float(np.std(fold_scores)),
        "fold_scores": fold_scores,
    }

    return best_model, metrics


def _extract_importance(
    model: Any, feature_names: list[str],
) -> dict[str, float]:
    """피처 중요도를 추출한다."""
    try:
        raw = model.feature_importance(importance_type="gain")  # type: ignore[union-attr]
        total = sum(raw) if sum(raw) > 0 else 1
        return {
            name: float(val / total)
            for name, val in zip(feature_names, raw)
        }
    except Exception as exc:
        logger.warning("피처 중요도 추출 실패 (0.0 폴백): %s", exc)
        return {name: 0.0 for name in feature_names}


def _save_model(model: Any, version: str) -> str:
    """모델을 파일로 저장한다."""
    model_dir = _ensure_model_dir()
    path = model_dir / f"lgbm_{version}.txt"
    model.save_model(str(path))  # type: ignore[union-attr]
    return str(path)


def train_model(
    feature_matrix: FeatureMatrix,
    label_vector: LabelVector,
    params: dict | None = None,
) -> TrainedModel:
    """LightGBM 모델을 TimeSeriesSplit으로 학습하고 저장한다.

    5-fold TimeSeriesSplit 교차검증으로 AUC를 측정하며,
    최종 모델을 data/models/ 디렉토리에 저장한다.
    """
    logger.info(
        "LightGBM 학습 시작: %d행 x %d피처",
        feature_matrix.row_count, len(feature_matrix.feature_names),
    )

    model, metrics = _train_with_cv(
        feature_matrix.features,
        label_vector.labels,
        feature_matrix.feature_names,
        params,
    )

    # 데이터 부족으로 모델이 생성되지 않은 경우 빈 결과를 반환한다
    if model is None:
        logger.warning("모델 미생성 — 데이터 부족으로 학습을 건너뛴다")
        return TrainedModel(
            model_path="",
            metrics=metrics,
            feature_importance={n: 0.0 for n in feature_matrix.feature_names},
            training_date=datetime.now(tz=timezone.utc),
        )

    importance = _extract_importance(model, feature_matrix.feature_names)

    now = datetime.now(tz=timezone.utc)
    version = now.strftime("%Y%m%d_%H%M%S")
    model_path = _save_model(model, version)

    logger.info("학습 완료: AUC=%.4f, 경로=%s", metrics["avg_auc"], model_path)

    return TrainedModel(
        model_path=model_path,
        metrics=metrics,
        feature_importance=importance,
        training_date=now,
    )

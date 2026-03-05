"""F8 ML -- Optuna TPE 200-trial 하이퍼파라미터 최적화이다."""

from __future__ import annotations

from src.common.logger import get_logger
from src.optimization.models import OptimizedParams

logger = get_logger(__name__)

_N_TRIALS: int = 200
_N_CV_SPLITS: int = 5
_NUM_BOOST_ROUND: int = 200


def _create_objective(
    features: list[list[float]], labels: list[int],
) -> object:
    """Optuna objective 함수를 생성한다."""
    try:
        import lightgbm as lgb
        import numpy as np
        import optuna
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import TimeSeriesSplit
    except ImportError as exc:
        raise ImportError(
            "optuna, lightgbm, scikit-learn 설치 필요: "
            "pip install optuna lightgbm scikit-learn"
        ) from exc

    x_arr = np.array(features)
    y_arr = np.array(labels)

    def objective(trial: optuna.Trial) -> float:
        """단일 trial의 AUC를 반환한다."""
        params = {
            "objective": "binary",
            "metric": "auc",
            "boosting_type": "gbdt",
            "verbose": -1,
            "num_leaves": trial.suggest_int("num_leaves", 15, 63),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
            "lambda_l1": trial.suggest_float("lambda_l1", 1e-8, 10.0, log=True),
            "lambda_l2": trial.suggest_float("lambda_l2", 1e-8, 10.0, log=True),
        }

        tscv = TimeSeriesSplit(n_splits=_N_CV_SPLITS)
        scores: list[float] = []

        for train_idx, val_idx in tscv.split(x_arr):
            dtrain = lgb.Dataset(x_arr[train_idx], label=y_arr[train_idx])
            dval = lgb.Dataset(x_arr[val_idx], label=y_arr[val_idx])

            model = lgb.train(
                params, dtrain,
                num_boost_round=_NUM_BOOST_ROUND,
                valid_sets=[dval],
            )
            preds = model.predict(x_arr[val_idx])
            scores.append(roc_auc_score(y_arr[val_idx], preds))

        return float(np.mean(scores))

    return objective


def optimize_params(
    features: list[list[float]], labels: list[int],
) -> OptimizedParams:
    """TPE 알고리즘으로 LightGBM 하이퍼파라미터를 최적화한다.

    200회 trial을 실행하여 AUC가 가장 높은 파라미터 조합을 찾는다.
    Optuna의 TPE(Tree-structured Parzen Estimator) 샘플러를 사용한다.
    """
    try:
        import optuna
    except ImportError as exc:
        raise ImportError(
            "optuna 설치 필요: pip install optuna"
        ) from exc

    logger.info("Optuna 최적화 시작: %d trials", _N_TRIALS)

    # 불필요한 로그를 억제한다
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    objective = _create_objective(features, labels)
    study.optimize(objective, n_trials=_N_TRIALS)

    best = study.best_trial
    logger.info(
        "최적화 완료: best_auc=%.4f, trials=%d",
        best.value, len(study.trials),
    )

    return OptimizedParams(
        best_params=best.params,
        best_score=best.value,
        trials_count=len(study.trials),
    )

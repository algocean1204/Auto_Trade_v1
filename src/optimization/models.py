"""F8 최적화 -- 공용 모델이다."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DateRange(BaseModel):
    """학습 데이터 조회 기간이다."""

    start: datetime
    end: datetime


class PreparedData(BaseModel):
    """정제된 학습 데이터이다."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: list[dict]
    row_count: int
    date_range: str


class FeatureMatrix(BaseModel):
    """21개 피처가 포함된 피처 행렬이다."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    features: list[list[float]]
    feature_names: list[str]
    row_count: int


class LabelVector(BaseModel):
    """타겟 라벨 벡터이다."""

    labels: list[int]
    positive_ratio: float


class TrainedModel(BaseModel):
    """학습 완료된 모델 메타데이터이다."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_path: str
    metrics: dict
    feature_importance: dict[str, float]
    training_date: datetime


class OptimizedParams(BaseModel):
    """Optuna 최적화 결과 파라미터이다."""

    best_params: dict
    best_score: float
    trials_count: int


class WalkForwardResult(BaseModel):
    """Walk-Forward 검증 결과이다."""

    folds: int
    avg_score: float
    stability: float
    fold_scores: list[float]


class TrainingReport(BaseModel):
    """주간 자동 학습 보고서이다."""

    model_version: str
    metrics: dict
    deployed: bool


class TimeTravelResult(BaseModel):
    """분봉 리플레이 임베딩 결과이다."""

    embeddings_count: int
    patterns_found: int


class KnowledgeResult(BaseModel):
    """RAG 검색 결과이다."""

    documents: list[dict]
    scores: list[float]
    embedding_count: int


class ExecutionOptimizerResult(BaseModel):
    """실행 최적화 결과이다."""

    adjusted_params: dict
    changes: list[str]
    backup_path: str

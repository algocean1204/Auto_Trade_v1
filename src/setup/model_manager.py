"""F7.6 ModelManager -- GGUF 모델 다운로드 관리자이다.

4개 로컬 LLM 모델(Bllossom, Qwen, Llama, DeepSeek)의
다운로드 상태 확인, HuggingFace Hub 다운로드, 취소를 관리한다.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.monitoring.schemas.setup_schemas import ModelsStatusResponse

from src.common.logger import get_logger
from src.common.paths import get_models_dir

logger: logging.Logger = get_logger(__name__)

# ── 모델 레지스트리 ────────────────────────────────────

_MODEL_REGISTRY: list[dict[str, Any]] = [
    {
        "model_id": "bllossom-8b",
        "name": "Bllossom-8B (번역 전용)",
        "repo_id": "Bllossom/llama-3-Korean-Bllossom-8B-gguf",
        "filename": "llama-3-Korean-Bllossom-8B.Q8_0.gguf",
        "size_gb": 8.5,
    },
    {
        "model_id": "qwen-7b",
        "name": "Qwen2.5-7B (분류 앙상블)",
        "repo_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "size_gb": 4.7,
    },
    {
        "model_id": "llama-8b",
        "name": "Llama-3.1-8B (분류 앙상블)",
        "repo_id": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "filename": "Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf",
        "size_gb": 4.9,
    },
    {
        "model_id": "deepseek-8b",
        "name": "DeepSeek-R1-8B (분류 앙상블)",
        "repo_id": "bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF",
        "filename": "DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf",
        "size_gb": 4.9,
    },
]

# ── 모듈 수준 상태 ─────────────────────────────────────

_download_progress: dict[str, float] = {}
_cancel_flag: bool = False
_downloading: bool = False


def _model_path(filename: str) -> Path:
    """모델 파일의 절대 경로를 반환한다."""
    return get_models_dir() / filename


def _is_downloaded(filename: str) -> bool:
    """모델 파일이 존재하는지 확인한다."""
    return _model_path(filename).exists()


# ── 상태 조회 ──────────────────────────────────────────

def get_models_status() -> dict[str, Any]:
    """전체 모델 다운로드 현황 요약을 dict로 반환한다."""
    downloaded = sum(1 for m in _MODEL_REGISTRY if _is_downloaded(m["filename"]))
    total = len(_MODEL_REGISTRY)
    return {
        "all_downloaded": downloaded == total,
        "downloaded_count": downloaded,
        "total_count": total,
    }


def get_detailed_models_status() -> ModelsStatusResponse:
    """4개 모델의 상세 다운로드 현황을 ModelsStatusResponse로 반환한다."""
    from src.monitoring.schemas.setup_schemas import ModelInfo, ModelsStatusResponse

    models: list[ModelInfo] = []
    downloaded_count = 0
    total_size = 0.0

    for entry in _MODEL_REGISTRY:
        is_done = _is_downloaded(entry["filename"])
        if is_done:
            downloaded_count += 1
        progress = _download_progress.get(entry["model_id"])
        models.append(ModelInfo(
            model_id=entry["model_id"],
            name=entry["name"],
            repo_id=entry["repo_id"],
            filename=entry["filename"],
            size_gb=entry["size_gb"],
            downloaded=is_done,
            download_progress=progress,
        ))
        total_size += entry["size_gb"]

    return ModelsStatusResponse(
        models=models,
        total_size_gb=round(total_size, 1),
        downloaded_count=downloaded_count,
        total_count=len(_MODEL_REGISTRY),
    )


# ── 다운로드 ───────────────────────────────────────────

def _sync_download_one(entry: dict[str, Any]) -> bool:
    """단일 모델을 동기로 다운로드한다. resume 지원이다."""
    global _cancel_flag
    model_id: str = entry["model_id"]

    if _cancel_flag:
        return False

    if _is_downloaded(entry["filename"]):
        logger.info("모델 이미 존재, 건너뜀: %s", entry["filename"])
        _download_progress[model_id] = 1.0
        return True

    try:
        from huggingface_hub import hf_hub_download  # type: ignore[import-untyped]
    except ImportError:
        logger.error("huggingface_hub 미설치. pip install huggingface-hub 필요")
        return False

    logger.info("다운로드 시작: %s (%.1fGB)", entry["name"], entry["size_gb"])
    _download_progress[model_id] = 0.0

    try:
        hf_hub_download(
            repo_id=entry["repo_id"],
            filename=entry["filename"],
            local_dir=str(get_models_dir()),
            local_dir_use_symlinks=False,
        )
        _download_progress[model_id] = 1.0
        logger.info("다운로드 완료: %s", entry["name"])
        return True
    except Exception:
        logger.exception("다운로드 실패: %s", entry["name"])
        _download_progress.pop(model_id, None)
        return False


async def start_download(model_ids: list[str] | None = None) -> None:
    """지정 모델을 백그라운드로 다운로드한다. None이면 전체 다운로드이다."""
    global _cancel_flag, _downloading

    if _downloading:
        logger.warning("이미 다운로드가 진행 중이다")
        return

    _cancel_flag = False
    _downloading = True

    if model_ids is None:
        targets = list(_MODEL_REGISTRY)
    else:
        id_set = set(model_ids)
        targets = [m for m in _MODEL_REGISTRY if m["model_id"] in id_set]

    if not targets:
        logger.warning("다운로드할 모델이 없다")
        _downloading = False
        return

    loop = asyncio.get_running_loop()
    try:
        for entry in targets:
            if _cancel_flag:
                logger.info("다운로드 취소됨 — 남은 모델 건너뜀")
                break
            await loop.run_in_executor(None, _sync_download_one, entry)
    finally:
        _downloading = False
        if not _cancel_flag:
            logger.info("모든 모델 다운로드 작업 완료")


async def cancel_download() -> None:
    """진행 중인 다운로드에 취소 플래그를 설정한다."""
    global _cancel_flag
    _cancel_flag = True
    logger.info("모델 다운로드 취소 요청됨")

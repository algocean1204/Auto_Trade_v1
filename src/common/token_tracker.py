"""토큰 사용량 추적 모듈이다.

API 호출(과금)과 SDK/OAuth 구독 호출(구독 포함)을 분리 측정한다.
- API: Anthropic API 키 사용, 토큰당 과금 → 실제 비용 계산
- SDK: Claude CLI(OAuth 구독), 구독에 포함 → 토큰 수만 기록 (비용 0)
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_data_dir

_logger = get_logger(__name__)


def _tracker_file() -> Path:
    """토큰 사용량 JSON 파일 경로를 반환한다."""
    return get_data_dir() / "token_usage.json"

# API 호출 전용 비용표 ($ per 1M tokens, 2026-03 기준)
# SDK 호출은 구독에 포함이므로 비용 계산하지 않는다
_API_COST_TABLE: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
}

_lock = threading.Lock()

# 세션 시작 시간이다
_session_start: float = time.time()

# 인메모리 누적 데이터: source별 분리 저장한다
_api_usage: dict[str, dict[str, int | float]] = {}
_sdk_usage: dict[str, dict[str, int | float]] = {}

# 디스크 저장 스로틀: 최소 30초 간격으로만 파일에 쓴다 (매 호출마다 쓰면 I/O 병목)
_last_save_time: float = 0.0
_SAVE_INTERVAL_SEC: float = 30.0
_dirty: bool = False


def _get_store(source: str) -> dict[str, dict[str, int | float]]:
    """source에 따른 저장소를 반환한다."""
    return _api_usage if source == "api" else _sdk_usage


def record_usage(
    model: str,
    source: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """토큰 사용량을 기록한다. API/SDK 분리 저장, 쓰레드 안전하다."""
    with _lock:
        store = _get_store(source)
        if model not in store:
            store[model] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "errors": 0,
            }

        entry = store[model]
        entry["calls"] += 1  # type: ignore[operator]
        entry["input_tokens"] += input_tokens  # type: ignore[operator]
        entry["output_tokens"] += output_tokens  # type: ignore[operator]

        _save_throttled()


def record_error(model: str, source: str) -> None:
    """AI 호출 실패를 기록한다."""
    with _lock:
        store = _get_store(source)
        if model not in store:
            store[model] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "errors": 0,
            }
        store[model]["errors"] += 1  # type: ignore[operator]
        _save_throttled()


def _calc_api_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """API 호출 비용을 계산한다. SDK는 0을 반환한다."""
    cost_info = _API_COST_TABLE.get(model, {"input": 3.0, "output": 15.0})
    return (input_tokens * cost_info["input"] + output_tokens * cost_info["output"]) / 1_000_000


def _summarize_store(store: dict[str, dict[str, int | float]], is_api: bool) -> dict:
    """단일 저장소(api 또는 sdk)를 요약한다."""
    total_calls = sum(int(e["calls"]) for e in store.values())
    total_input = sum(int(e["input_tokens"]) for e in store.values())
    total_output = sum(int(e["output_tokens"]) for e in store.values())
    total_errors = sum(int(e["errors"]) for e in store.values())

    total_cost = 0.0
    models: dict[str, dict] = {}
    for model, entry in store.items():
        inp = int(entry["input_tokens"])
        out = int(entry["output_tokens"])
        cost = _calc_api_cost(model, inp, out) if is_api else 0.0
        total_cost += cost
        models[model] = {
            "calls": int(entry["calls"]),
            "input_tokens": inp,
            "output_tokens": out,
            "errors": int(entry["errors"]),
            "cost_usd": round(cost, 4) if is_api else 0.0,
        }

    return {
        "total_calls": total_calls,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_errors": total_errors,
        "total_cost_usd": round(total_cost, 4) if is_api else 0.0,
        "billing": "per_token" if is_api else "subscription",
        "models": models,
    }


def get_summary() -> dict:
    """현재 세션의 토큰 사용량 요약을 반환한다. API/SDK 분리 표시한다."""
    with _lock:
        elapsed_min = (time.time() - _session_start) / 60.0
        api_summary = _summarize_store(_api_usage, is_api=True)
        sdk_summary = _summarize_store(_sdk_usage, is_api=False)

        return {
            "session_start": _session_start,
            "elapsed_minutes": round(elapsed_min, 1),
            "api": api_summary,
            "sdk": sdk_summary,
            "combined": {
                "total_calls": api_summary["total_calls"] + sdk_summary["total_calls"],
                "total_tokens": api_summary["total_tokens"] + sdk_summary["total_tokens"],
                "total_errors": api_summary["total_errors"] + sdk_summary["total_errors"],
                "api_cost_usd": api_summary["total_cost_usd"],
            },
        }


def reset_session() -> None:
    """세션 카운터를 초기화한다. 매매 시작 시 호출한다."""
    global _session_start, _dirty, _last_save_time
    with _lock:
        _api_usage.clear()
        _sdk_usage.clear()
        _session_start = time.time()
        _dirty = False
        _last_save_time = 0.0
        _save_to_file()
    _logger.info("토큰 추적 세션 초기화 완료")


def flush() -> None:
    """더티 데이터가 있으면 즉시 파일에 저장한다. EOD 등에서 호출한다."""
    global _dirty, _last_save_time
    with _lock:
        if _dirty:
            _save_to_file()
            _dirty = False
            _last_save_time = time.time()


def _save_throttled() -> None:
    """최소 _SAVE_INTERVAL_SEC 간격으로만 디스크에 저장한다.

    매 AI 호출마다 파일 쓰기를 하면 I/O 병목이 된다.
    _lock을 보유한 상태에서 호출해야 한다.
    """
    global _dirty, _last_save_time
    _dirty = True
    now = time.time()
    if now - _last_save_time >= _SAVE_INTERVAL_SEC:
        _save_to_file()
        _dirty = False
        _last_save_time = now


def _save_to_file() -> None:
    """현재 사용량을 JSON 파일로 저장한다. _lock 보유 상태에서 호출한다."""
    try:
        tracker = _tracker_file()
        tracker.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "session_start": _session_start,
            "updated_at": time.time(),
            "api": {model: dict(entry) for model, entry in _api_usage.items()},
            "sdk": {model: dict(entry) for model, entry in _sdk_usage.items()},
        }
        import os
        import tempfile
        content = json.dumps(data, indent=2, default=str)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(tracker.parent), suffix=".tmp",
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
            os.replace(tmp_path, str(tracker))
        except BaseException:
            os.unlink(tmp_path)
            raise
    except Exception:
        _logger.debug("토큰 사용량 파일 저장 실패", exc_info=True)

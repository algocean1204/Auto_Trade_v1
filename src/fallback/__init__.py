"""
Fallback 모듈

Claude API 장애 또는 Quota 초과 시 로컬 Qwen3 모델로 자동 전환하는 시스템.
"""

from src.fallback.fallback_router import FallbackRouter
from src.fallback.local_model import LocalModel

__all__ = [
    "FallbackRouter",
    "LocalModel",
]

"""
로컬 AI 분류 파이프라인 모듈

Qwen3-30B-A3B MoE 모델을 MLX로 서빙하여 뉴스 분류를 로컬에서 수행하고,
ChromaDB + bge-m3 RAG로 미지용어를 자동 학습한다.
"""

from src.ai.mlx_classifier import MLXClassifier
from src.ai.knowledge_manager import KnowledgeManager

__all__ = [
    "MLXClassifier",
    "KnowledgeManager",
]

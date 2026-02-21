"""
bge-m3 multilingual embedding model wrapper.

- 1024-dimensional Dense vectors (primary)
- FP16 mode optimized for M4 Pro Apple Silicon
- Supports English, Korean, Chinese, Japanese
- Memory footprint: ~3GB

Falls back to sentence-transformers all-MiniLM-L6-v2 (384-dim) if
FlagEmbedding is not available.
"""

import logging
from typing import ClassVar

import numpy as np

logger = logging.getLogger(__name__)

# Sentinel to track which backend is loaded
_BACKEND: str | None = None


def _load_bge_model():
    """Attempt to load BAAI/bge-m3 via FlagEmbedding."""
    global _BACKEND
    try:
        from FlagEmbedding import BGEM3FlagModel

        model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
        _BACKEND = "bge-m3"
        logger.info("Loaded bge-m3 embedding model (1024-dim, FP16)")
        return model, 1024
    except Exception as exc:
        logger.warning(
            "Failed to load bge-m3 model: %s. "
            "Falling back to all-MiniLM-L6-v2 (384-dim). "
            "WARNING: Embedding dimension changes from 1024 to 384. "
            "Vectors stored with a different dimension are incompatible.",
            exc,
        )
        return None, None


def _load_fallback_model():
    """Load sentence-transformers all-MiniLM-L6-v2 as fallback."""
    global _BACKEND
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    _BACKEND = "all-MiniLM-L6-v2"
    logger.warning(
        "Using fallback embedding model: all-MiniLM-L6-v2 (384-dim). "
        "This produces 384-dim vectors instead of 1024-dim. "
        "Existing 1024-dim embeddings in the database will NOT be compatible."
    )
    return model, 384


class BGEEmbedder:
    """Singleton embedding model wrapper.

    Uses bge-m3 (1024-dim) by default; falls back to all-MiniLM-L6-v2
    (384-dim) when FlagEmbedding is unavailable.
    """

    _instance: ClassVar["BGEEmbedder | None"] = None

    def __init__(self) -> None:
        model, dim = _load_bge_model()
        if model is not None:
            self._bge_model = model
            self._fallback_model = None
            self.dimension: int = dim
        else:
            self._bge_model = None
            fb_model, fb_dim = _load_fallback_model()
            self._fallback_model = fb_model
            self.dimension = fb_dim

        self.backend: str = _BACKEND or "unknown"
        logger.info(
            "BGEEmbedder initialized: backend=%s, dimension=%d",
            self.backend,
            self.dimension,
        )

    @classmethod
    def get_instance(cls) -> "BGEEmbedder":
        """Return the singleton embedder instance, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (useful for testing)."""
        cls._instance = None

    def encode(
        self,
        texts: list[str],
        batch_size: int = 32,
        max_length: int = 512,
    ) -> np.ndarray:
        """Encode texts into dense vectors.

        Args:
            texts: List of strings to embed.
            batch_size: Batch size for encoding.
            max_length: Maximum token length per text.

        Returns:
            np.ndarray of shape ``(len(texts), self.dimension)``.
        """
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        if self._bge_model is not None:
            result = self._bge_model.encode(
                texts,
                batch_size=batch_size,
                max_length=max_length,
            )
            return result["dense_vecs"]

        # Fallback: sentence-transformers
        vectors = self._fallback_model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_single(self, text: str) -> list[float]:
        """Encode a single text and return as a Python list of floats."""
        vec = self.encode([text])[0]
        return vec.tolist()

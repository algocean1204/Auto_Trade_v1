"""F8 RAG -- ChromaDB + BGE-M3 지식 관리이다."""

from __future__ import annotations

import hashlib
from datetime import datetime

from src.common.logger import get_logger
from src.optimization.models import KnowledgeResult

logger = get_logger(__name__)

# ChromaDB 컬렉션 이름이다
_COLLECTION_NAME: str = "trading_knowledge"

# BGE-M3 모델 이름이다
_EMBEDDING_MODEL: str = "BAAI/bge-m3"

# 검색 시 반환할 최대 문서 수이다
_TOP_K: int = 5


def _get_chroma_client() -> object:
    """ChromaDB 클라이언트를 생성한다."""
    try:
        import chromadb
    except ImportError as exc:
        raise ImportError(
            "chromadb 설치 필요: pip install chromadb"
        ) from exc

    from pathlib import Path
    persist_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "chromadb"
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def _get_embedding_fn() -> object:
    """BGE-M3 임베딩 함수를 생성한다."""
    try:
        from chromadb.utils.embedding_functions import (
            SentenceTransformerEmbeddingFunction,
        )
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers 설치 필요: "
            "pip install sentence-transformers"
        ) from exc

    return SentenceTransformerEmbeddingFunction(
        model_name=_EMBEDDING_MODEL,
    )


def _get_collection(client: object, embed_fn: object) -> object:
    """ChromaDB 컬렉션을 가져오거나 생성한다."""
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=embed_fn,
    )


def _generate_doc_id(content: str) -> str:
    """문서 내용의 해시로 고유 ID를 생성한다."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class KnowledgeManager:
    """ChromaDB + BGE-M3 RAG 지식 관리자이다.

    거래 패턴, 분석 결과, 학습 내용을 임베딩하여 저장하고
    유사도 검색으로 관련 지식을 검색한다.
    """

    def __init__(self) -> None:
        """ChromaDB 클라이언트와 임베딩 함수를 초기화한다."""
        self._client = _get_chroma_client()
        self._embed_fn = _get_embedding_fn()
        self._collection = _get_collection(self._client, self._embed_fn)
        logger.info("KnowledgeManager 초기화 완료")

    def store_document(
        self,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """문서를 ChromaDB에 저장하고 임베딩한다.

        중복 문서는 해시 기반으로 자동 감지하여 덮어쓴다.
        """
        doc_id = _generate_doc_id(content)
        meta = metadata or {}
        meta["stored_at"] = datetime.now().isoformat()

        self._collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[meta],
        )

        logger.info("문서 저장: id=%s, len=%d", doc_id, len(content))
        return doc_id

    def search(
        self,
        query: str,
        top_k: int = _TOP_K,
    ) -> KnowledgeResult:
        """쿼리와 유사한 문서를 검색한다.

        BGE-M3 임베딩으로 코사인 유사도 기반 검색을 수행한다.
        """
        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
        )

        documents: list[dict] = []
        scores: list[float] = []

        if results and results.get("documents"):
            docs = results["documents"][0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]

            for i, doc in enumerate(docs):
                documents.append({
                    "content": doc,
                    "metadata": metas[i] if i < len(metas) else {},
                })
                # ChromaDB distance → similarity 변환이다
                dist = dists[i] if i < len(dists) else 1.0
                scores.append(max(0.0, 1.0 - dist))

        count = self._collection.count()
        logger.info(
            "검색 완료: query='%s', 결과=%d건, 총 문서=%d",
            query[:50], len(documents), count,
        )

        return KnowledgeResult(
            documents=documents,
            scores=scores,
            embedding_count=count,
        )

    def count(self) -> int:
        """저장된 문서 수를 반환한다."""
        return self._collection.count()

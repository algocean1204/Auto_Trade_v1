"""
RAG document manager: CRUD operations for rag_documents table.

Handles document creation with automatic embedding generation,
updates with conditional re-embedding, relevance score adjustments,
and periodic cleanup of stale documents.

Document types (6 categories):
- ticker_profile: Ticker characteristics, past patterns, warnings (weekly update)
- trade_lesson: Lessons from past loss/profit trades (per trade)
- event_playbook: Event response playbook (manual + weekly enrichment)
- technical_pattern: Ticker-specific technical indicator patterns (daily)
- strategy_rule: Accumulated strategy rules (weekly)
- macro_context: Macro environment summary (weekly)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RagDocument
from src.rag.embedder import BGEEmbedder

logger = logging.getLogger(__name__)

DOC_TYPES = frozenset({
    "ticker_profile",
    "trade_lesson",
    "event_playbook",
    "technical_pattern",
    "strategy_rule",
    "macro_context",
})


class RAGDocManager:
    """CRUD manager for RAG documents with automatic embedding lifecycle."""

    def __init__(self, db_session: AsyncSession, embedder: BGEEmbedder) -> None:
        self.db = db_session
        self.embedder = embedder

    async def create(self, doc: dict[str, Any]) -> str:
        """Create a new RAG document with auto-generated embedding.

        Args:
            doc: Dict with keys: doc_type (required), title (required),
                 content (required), ticker (optional), source (optional),
                 metadata (optional), relevance_score (optional, default 1.0).

        Returns:
            The generated document UUID string.

        Raises:
            ValueError: If doc_type is invalid or required fields are missing.
        """
        doc_type = doc.get("doc_type", "")
        if doc_type not in DOC_TYPES:
            raise ValueError(
                f"Invalid doc_type '{doc_type}'. Must be one of: {sorted(DOC_TYPES)}"
            )

        title = doc.get("title")
        content = doc.get("content")
        if not title or not content:
            raise ValueError("Both 'title' and 'content' are required")

        doc_id = str(uuid4())

        # Generate embedding from title + content
        embed_text = f"{title}\n{content}"
        embedding = self.embedder.encode_single(embed_text)

        record = RagDocument(
            id=doc_id,
            doc_type=doc_type,
            ticker=doc.get("ticker"),
            title=title,
            content=content,
            metadata_=doc.get("metadata", {}),
            embedding=embedding,
            source=doc.get("source"),
            relevance_score=doc.get("relevance_score", 1.0),
        )
        self.db.add(record)
        await self.db.flush()

        logger.info(
            "Created RAG document: id=%s type=%s ticker=%s title=%r",
            doc_id,
            doc_type,
            doc.get("ticker"),
            title[:60],
        )
        return doc_id

    async def get(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve a single document by ID.

        Returns:
            Document dict or None if not found.
        """
        stmt = select(RagDocument).where(RagDocument.id == doc_id)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def update(self, doc_id: str, updates: dict[str, Any]) -> bool:
        """Update an existing document.

        If ``content`` or ``title`` is changed, the embedding is regenerated.

        Args:
            doc_id: Document UUID.
            updates: Fields to update. Supported: title, content, ticker,
                     metadata, source, relevance_score.

        Returns:
            True if the document was found and updated, False otherwise.
        """
        stmt = select(RagDocument).where(RagDocument.id == doc_id)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            logger.warning("Document not found for update: %s", doc_id)
            return False

        needs_reembed = False

        if "title" in updates:
            row.title = updates["title"]
            needs_reembed = True
        if "content" in updates:
            row.content = updates["content"]
            needs_reembed = True
        if "ticker" in updates:
            row.ticker = updates["ticker"]
        if "metadata" in updates:
            row.metadata_ = updates["metadata"]
        if "source" in updates:
            row.source = updates["source"]
        if "relevance_score" in updates:
            row.relevance_score = float(updates["relevance_score"])

        if needs_reembed:
            embed_text = f"{row.title}\n{row.content}"
            row.embedding = self.embedder.encode_single(embed_text)
            logger.info("Re-embedded document %s after content/title change", doc_id)

        row.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info("Updated RAG document: id=%s fields=%s", doc_id, list(updates.keys()))
        return True

    async def delete(self, doc_id: str) -> bool:
        """Delete a document by ID.

        Returns:
            True if a document was deleted, False if not found.
        """
        stmt = delete(RagDocument).where(RagDocument.id == doc_id)
        result = await self.db.execute(stmt)
        deleted = result.rowcount > 0
        if deleted:
            logger.info("Deleted RAG document: id=%s", doc_id)
        else:
            logger.warning("Document not found for deletion: %s", doc_id)
        return deleted

    async def list_by_type(
        self, doc_type: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List documents filtered by type, ordered by creation date descending.

        Args:
            doc_type: Document type to filter by.
            limit: Maximum number of results.

        Returns:
            List of document dicts.
        """
        stmt = (
            select(RagDocument)
            .where(RagDocument.doc_type == doc_type)
            .order_by(RagDocument.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_dict(r) for r in rows]

    async def list_by_ticker(
        self, ticker: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List documents filtered by ticker, ordered by creation date descending.

        Args:
            ticker: Ticker symbol to filter by.
            limit: Maximum number of results.

        Returns:
            List of document dicts.
        """
        stmt = (
            select(RagDocument)
            .where(RagDocument.ticker == ticker)
            .order_by(RagDocument.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_dict(r) for r in rows]

    async def adjust_relevance(self, doc_id: str, delta: float) -> float | None:
        """Adjust a document's relevance_score by delta.

        The score is clamped to [0.0, 5.0].

        Args:
            doc_id: Document UUID.
            delta: Amount to add (positive) or subtract (negative).

        Returns:
            New relevance_score, or None if document not found.
        """
        stmt = select(RagDocument).where(RagDocument.id == doc_id)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            logger.warning("Document not found for relevance adjustment: %s", doc_id)
            return None

        new_score = max(0.0, min(5.0, row.relevance_score + delta))
        row.relevance_score = new_score
        row.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info(
            "Adjusted relevance for %s: delta=%.2f -> new_score=%.2f",
            doc_id,
            delta,
            new_score,
        )
        return new_score

    async def cleanup_old_docs(
        self,
        days: int = 90,
        doc_types: list[str] | None = None,
    ) -> int:
        """Delete documents older than *days*.

        Args:
            days: Age threshold in days.
            doc_types: If provided, only clean up these document types.
                       Defaults to all types except ``event_playbook``
                       and ``strategy_rule`` (which are manually curated).

        Returns:
            Number of documents deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Default: clean up auto-generated types, preserve curated ones
        types_to_clean = doc_types or [
            "ticker_profile",
            "trade_lesson",
            "technical_pattern",
            "macro_context",
        ]

        stmt = (
            delete(RagDocument)
            .where(RagDocument.created_at < cutoff)
            .where(RagDocument.doc_type.in_(types_to_clean))
        )
        result = await self.db.execute(stmt)
        count = result.rowcount

        logger.info(
            "Cleaned up %d old RAG documents (older than %d days, types=%s)",
            count,
            days,
            types_to_clean,
        )
        return count

    @staticmethod
    def _row_to_dict(row: RagDocument) -> dict[str, Any]:
        """Convert an ORM row to a plain dict."""
        return {
            "id": str(row.id),
            "doc_type": row.doc_type,
            "ticker": row.ticker,
            "title": row.title,
            "content": row.content,
            "metadata": row.metadata_,
            "source": row.source,
            "relevance_score": float(row.relevance_score),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

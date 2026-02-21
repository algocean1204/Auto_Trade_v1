"""
RAG retriever with pgvector cosine similarity search.

Searches the ``rag_documents`` table for relevant context to inject into
Claude prompts during trade decision-making.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.rag.embedder import BGEEmbedder

logger = logging.getLogger(__name__)

# Valid document types for filtering
DOC_TYPES = frozenset({
    "ticker_profile",
    "trade_lesson",
    "event_playbook",
    "technical_pattern",
    "strategy_rule",
    "macro_context",
})


class RAGRetriever:
    """Vector similarity search over RAG documents stored in pgvector."""

    def __init__(self, db_session: AsyncSession, embedder: BGEEmbedder) -> None:
        self.db = db_session
        self.embedder = embedder

    async def search(
        self,
        query: str,
        ticker: str | None = None,
        doc_types: list[str] | None = None,
        top_k: int = 8,
        min_similarity: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Search for documents similar to *query* using cosine similarity.

        Args:
            query: Natural-language search query.
            ticker: Filter by specific ticker symbol (optional).
            doc_types: Filter by document types (optional).
            top_k: Maximum number of results.
            min_similarity: Minimum cosine similarity threshold (0-1).

        Returns:
            List of dicts with keys: id, doc_type, ticker, title, content,
            similarity, relevance_score, source.
        """
        # 1. Embed query
        query_vec = self.embedder.encode_single(query)

        # 2. Build dynamic SQL
        conditions: list[str] = []
        params: dict[str, Any] = {
            "query_vec": str(query_vec),
            "min_sim": min_similarity,
            "top_k": top_k,
        }

        if ticker is not None:
            conditions.append("ticker = :ticker")
            params["ticker"] = ticker

        if doc_types:
            # Validate doc types
            valid = [dt for dt in doc_types if dt in DOC_TYPES]
            if not valid:
                logger.warning("No valid doc_types in %s, returning empty", doc_types)
                return []
            conditions.append("doc_type = ANY(:doc_types)")
            params["doc_types"] = valid

        where_clause = ""
        if conditions:
            where_clause = "AND " + " AND ".join(conditions)

        sql = text(f"""
            SELECT
                id,
                doc_type,
                ticker,
                title,
                content,
                source,
                relevance_score,
                1 - (embedding <=> CAST(:query_vec AS vector)) AS similarity
            FROM rag_documents
            WHERE embedding IS NOT NULL
              AND 1 - (embedding <=> CAST(:query_vec AS vector)) >= :min_sim
              {where_clause}
            ORDER BY similarity DESC
            LIMIT :top_k
        """)

        result = await self.db.execute(sql, params)
        rows = result.mappings().all()

        docs = [
            {
                "id": str(row["id"]),
                "doc_type": row["doc_type"],
                "ticker": row["ticker"],
                "title": row["title"],
                "content": row["content"],
                "source": row["source"],
                "relevance_score": float(row["relevance_score"]),
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]

        logger.debug(
            "RAG search: query=%r ticker=%s types=%s -> %d results",
            query[:80],
            ticker,
            doc_types,
            len(docs),
        )
        return docs

    async def build_context(
        self,
        signals: list[dict[str, Any]],
        positions: list[dict[str, Any]],
    ) -> str:
        """Build RAG context string for Claude trade decision prompts.

        Aggregates relevant documents from multiple categories:
        1. Ticker profiles and trade lessons for each ticker in signals/positions
        2. Technical patterns for signaled tickers
        3. Event playbooks and macro context for market regime awareness
        4. Strategy rules for general decision support

        Args:
            signals: List of signal dicts, each having at least a ``ticker`` key.
            positions: List of current position dicts, each with ``ticker``.

        Returns:
            Formatted context string ready for Claude prompt injection.
        """
        all_docs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # Collect unique tickers from signals and positions
        tickers: set[str] = set()
        for s in signals:
            if t := s.get("ticker"):
                tickers.add(t)
        for p in positions:
            if t := p.get("ticker"):
                tickers.add(t)

        # 1. Per-ticker searches: profile, lessons, patterns
        ticker_doc_types = ["ticker_profile", "trade_lesson", "technical_pattern"]
        for ticker in tickers:
            docs = await self.search(
                query=f"{ticker} trading characteristics and lessons",
                ticker=ticker,
                doc_types=ticker_doc_types,
                top_k=4,
                min_similarity=0.25,
            )
            for d in docs:
                if d["id"] not in seen_ids:
                    seen_ids.add(d["id"])
                    all_docs.append(d)

        # 2. Market-wide context: event playbooks, macro, strategy rules
        market_query_parts: list[str] = []
        for s in signals:
            if desc := s.get("description", s.get("signal_type", "")):
                market_query_parts.append(str(desc))
        market_query = " ".join(market_query_parts) if market_query_parts else "current market conditions"

        market_docs = await self.search(
            query=market_query,
            doc_types=["event_playbook", "macro_context", "strategy_rule"],
            top_k=6,
            min_similarity=0.25,
        )
        for d in market_docs:
            if d["id"] not in seen_ids:
                seen_ids.add(d["id"])
                all_docs.append(d)

        # 3. Sort by similarity descending, cap at 10 documents
        all_docs.sort(key=lambda d: d["similarity"], reverse=True)
        top_docs = all_docs[:10]

        if not top_docs:
            return ""

        logger.info(
            "RAG context built: %d documents (from %d unique tickers, %d signals)",
            len(top_docs),
            len(tickers),
            len(signals),
        )
        return self._format_context(top_docs)

    def _format_context(self, docs: list[dict[str, Any]]) -> str:
        """Format document list into a Claude-prompt-ready text block.

        Each document is rendered as::

            [doc_type] title (similarity: 0.XX)
            content...

        Separated by ``---``.
        """
        parts: list[str] = []
        for doc in docs:
            header = f"[{doc['doc_type']}] {doc['title']} (similarity: {doc['similarity']:.2f})"
            parts.append(f"{header}\n{doc['content']}")
        return "\n---\n".join(parts)

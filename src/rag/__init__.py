"""
RAG (Retrieval-Augmented Generation) system for the AI Auto-Trading System V2.

Provides:
- BGEEmbedder: bge-m3 multilingual embedding model wrapper
- RAGRetriever: pgvector cosine similarity search for trade context
- RAGDocManager: CRUD operations for RAG documents
- RAGDocGenerator: automatic document generation from feedback loops
"""

from src.rag.embedder import BGEEmbedder
from src.rag.retriever import RAGRetriever
from src.rag.doc_manager import RAGDocManager
from src.rag.doc_generator import RAGDocGenerator

__all__ = [
    "BGEEmbedder",
    "RAGRetriever",
    "RAGDocManager",
    "RAGDocGenerator",
]

"""
미지용어 자동감지 및 지식 DB 관리

분류 과정에서 미지용어를 감지하면 Claude Opus를 1회 호출하여
정의를 획득하고, ChromaDB에 영구 저장한다.

ChromaDB를 로컬 persistent storage로 사용하여
bge-m3 임베딩 기반 벡터 검색을 제공한다.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# chromadb는 선택적 의존성이므로 지연 임포트
_CHROMADB_AVAILABLE = False

try:
    import chromadb

    _CHROMADB_AVAILABLE = True
except ImportError:
    logger.warning("chromadb가 설치되어 있지 않다. KnowledgeManager를 사용할 수 없다.")

# 프로젝트 루트 기준 경로
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CHROMA_PATH = str(_PROJECT_ROOT / "data" / "chroma")
_DEFAULT_KNOWLEDGE_DIR = str(_PROJECT_ROOT / "knowledge")

# 미지용어 감지용 정규식: 대문자 약어, 하이픈 용어, 복합 금융 용어
_TERM_PATTERN = re.compile(
    r"\b(?:"
    r"[A-Z]{2,10}"                     # 대문자 약어 (ETF, CPI, GDP 등)
    r"|[A-Za-z]+-[A-Za-z]+"            # 하이픈 용어 (risk-off, carry-trade 등)
    r"|(?:[A-Z][a-z]+){2,}"            # PascalCase 복합어 (BlackSwan, DeathCross 등)
    r")\b"
)

# 일반적으로 금융 용어가 아닌 단어 (불필요한 학습 방지)
_COMMON_ABBREVIATIONS = frozenset({
    "THE", "AND", "FOR", "ARE", "NOT", "BUT", "ALL", "CAN", "HER",
    "WAS", "ONE", "OUR", "OUT", "HAS", "HIS", "HOW", "ITS", "LET",
    "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET",
    "HIM", "HIT", "HAD", "SAY", "SHE", "TOO", "USE", "CEO", "CFO",
    "API", "URL", "PDF", "USA", "USD", "EUR", "JPY", "KRW", "GBP",
})

# 용어 정의 요청 프롬프트
_TERM_DEFINITION_PROMPT = """You are a financial terminology expert.
Define the following financial term concisely in 2-3 sentences.
Include: what it is, why it matters for trading, and how it affects ETF/stock markets.

Term: {term}

Return ONLY a JSON object:
{{
    "term": "{term}",
    "definition": "your definition here",
    "category": "one of: macro, technical, instrument, risk, regulatory, strategy, other",
    "related_terms": ["list", "of", "related", "terms"]
}}"""

# ChromaDB 컬렉션 이름
_COLLECTION_NAME = "financial_knowledge"


class KnowledgeManager:
    """미지용어 자동감지 및 지식 DB 관리.

    분류 과정에서 미지용어를 감지하면 Claude Opus를 1회 호출하여
    정의를 획득하고, ChromaDB에 영구 저장한다.

    Attributes:
        chroma_client: ChromaDB 클라이언트.
        embedder: bge-m3 임베더.
        claude_client: Claude API 클라이언트 (미지용어 정의 조회용).
    """

    KNOWLEDGE_DIR: str = _DEFAULT_KNOWLEDGE_DIR

    def __init__(
        self,
        claude_client: Any,
        embedder: Any,
        chroma_path: str = _DEFAULT_CHROMA_PATH,
    ) -> None:
        """KnowledgeManager를 초기화한다.

        Args:
            claude_client: Claude API 클라이언트 (ClaudeClient 인스턴스).
            embedder: bge-m3 임베더 (BGEEmbedder 인스턴스).
            chroma_path: ChromaDB 영구 저장 경로.
        """
        self.claude_client = claude_client
        self.embedder = embedder
        self._chroma_path = chroma_path
        self._collection: Any = None
        self._initialized = False

        # knowledge 디렉토리 생성
        Path(self.KNOWLEDGE_DIR).mkdir(parents=True, exist_ok=True)

        logger.info(
            "KnowledgeManager 초기화 | chroma_path=%s | chromadb_available=%s",
            chroma_path,
            _CHROMADB_AVAILABLE,
        )

    def _ensure_initialized(self) -> bool:
        """ChromaDB 컬렉션이 초기화되었는지 확인하고, 필요하면 초기화한다.

        Returns:
            초기화 성공 여부.
        """
        if self._initialized and self._collection is not None:
            return True

        if not _CHROMADB_AVAILABLE:
            logger.error("chromadb 미설치로 KnowledgeManager 사용 불가")
            return False

        try:
            Path(self._chroma_path).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=self._chroma_path)
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            self._initialized = True
            logger.info(
                "ChromaDB 컬렉션 초기화 완료 | collection=%s | count=%d",
                _COLLECTION_NAME,
                self._collection.count(),
            )
            return True
        except Exception as exc:
            logger.error("ChromaDB 초기화 실패: %s", exc)
            return False

    async def load_initial_knowledge(self) -> int:
        """knowledge/ 디렉토리의 JSONL 파일들을 ChromaDB에 로드한다.

        companies.jsonl, products.jsonl, people.jsonl, terms.jsonl,
        supply_chain.jsonl 파일의 데이터를 임베딩하여 벡터 DB에 저장한다.
        이미 존재하는 문서는 upsert로 갱신된다.

        Returns:
            로드된 총 문서 수.
        """
        if not self._ensure_initialized():
            return 0

        knowledge_dir = Path(self.KNOWLEDGE_DIR)
        total_loaded = 0

        # 파일별 로드 함수 매핑
        loaders: list[tuple[str, str]] = [
            ("companies.jsonl", "company"),
            ("products.jsonl", "product"),
            ("people.jsonl", "person"),
            ("terms.jsonl", "term"),
            ("supply_chain.jsonl", "supply_chain"),
        ]

        for filename, doc_type in loaders:
            filepath = knowledge_dir / filename
            if not filepath.exists():
                logger.warning("초기 데이터 파일 없음: %s", filepath)
                continue

            count = await self._load_jsonl_file(filepath, doc_type)
            total_loaded += count
            logger.info(
                "초기 데이터 로드 완료 | file=%s | count=%d",
                filename,
                count,
            )

        logger.info(
            "초기 지식 데이터 로드 완료 | total=%d | collection_count=%d",
            total_loaded,
            self._collection.count() if self._collection else 0,
        )
        return total_loaded

    async def _load_jsonl_file(self, filepath: Path, doc_type: str) -> int:
        """단일 JSONL 파일을 읽어 ChromaDB에 저장한다.

        Args:
            filepath: JSONL 파일 경로.
            doc_type: 문서 유형 (company, product, person, term, supply_chain).

        Returns:
            저장된 문서 수.
        """
        if not self._collection:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str]] = []
        count = 0

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "JSONL 파싱 실패 | file=%s | line=%d | error=%s",
                            filepath.name,
                            line_num,
                            exc,
                        )
                        continue

                    doc_id, doc_text, metadata = self._entry_to_document(
                        entry, doc_type, line_num
                    )
                    if doc_id and doc_text:
                        ids.append(doc_id)
                        documents.append(doc_text)
                        metadatas.append(metadata)
                        count += 1

            if not ids:
                return 0

            # 배치 임베딩 생성
            embeddings_array = self.embedder.encode(documents)
            embeddings = [vec.tolist() for vec in embeddings_array]

            # 배치 upsert (ChromaDB 배치 제한 고려하여 분할)
            batch_size = 100
            for i in range(0, len(ids), batch_size):
                end = min(i + batch_size, len(ids))
                await asyncio.to_thread(
                    self._collection.upsert,
                    ids=ids[i:end],
                    embeddings=embeddings[i:end],
                    documents=documents[i:end],
                    metadatas=metadatas[i:end],
                )

            return count

        except Exception as exc:
            logger.error(
                "JSONL 파일 로드 실패 | file=%s | error=%s",
                filepath.name,
                exc,
            )
            return 0

    def _entry_to_document(
        self,
        entry: dict[str, Any],
        doc_type: str,
        line_num: int,
    ) -> tuple[str, str, dict[str, str]]:
        """JSONL 엔트리를 ChromaDB 문서 형식으로 변환한다.

        Args:
            entry: JSONL에서 파싱된 딕셔너리.
            doc_type: 문서 유형.
            line_num: 원본 파일의 줄 번호.

        Returns:
            (doc_id, doc_text, metadata) 튜플. 변환 실패 시 ("", "", {}).
        """
        try:
            if doc_type == "company":
                ticker = entry.get("ticker", "")
                names = entry.get("names", [])
                ceo = entry.get("ceo", "")
                ceo_kr = entry.get("ceo_kr", [])
                sector = entry.get("sector", "")
                etfs = entry.get("etfs", [])
                desc = entry.get("description", "")
                all_names = ", ".join(names)
                all_ceo = ", ".join([ceo] + ceo_kr) if ceo_kr else ceo
                all_etfs = ", ".join(etfs)
                doc_text = (
                    f"{ticker} ({all_names}): {desc}. "
                    f"CEO: {all_ceo}. Sector: {sector}. "
                    f"Related ETFs: {all_etfs}."
                )
                doc_id = f"company_{ticker.lower()}"
                metadata = {
                    "type": "company",
                    "ticker": ticker,
                    "sector": sector,
                    "source": "initial_data",
                }

            elif doc_type == "product":
                name = entry.get("name", "")
                company = entry.get("company", "")
                category = entry.get("category", "")
                aliases = entry.get("aliases", [])
                all_aliases = ", ".join(aliases)
                doc_text = (
                    f"{name} (aliases: {all_aliases}): "
                    f"Product by {company}. Category: {category}."
                )
                safe_name = name.lower().replace(" ", "_").replace("-", "_")
                doc_id = f"product_{safe_name}"
                metadata = {
                    "type": "product",
                    "company": company,
                    "category": category,
                    "source": "initial_data",
                }

            elif doc_type == "person":
                name = entry.get("name", "")
                aliases = entry.get("aliases", [])
                company = entry.get("company", "")
                role = entry.get("role", "")
                all_aliases = ", ".join(aliases)
                doc_text = (
                    f"{name} (aliases: {all_aliases}): "
                    f"{role} at {company}."
                )
                safe_name = name.lower().replace(" ", "_").replace("-", "_")
                doc_id = f"person_{safe_name}"
                metadata = {
                    "type": "person",
                    "company": company,
                    "role": role,
                    "source": "initial_data",
                }

            elif doc_type == "term":
                term = entry.get("term", "")
                definition = entry.get("definition", "")
                category = entry.get("category", "")
                related = entry.get("related", [])
                all_related = ", ".join(related)
                doc_text = (
                    f"{term}: {definition} "
                    f"Related: {all_related}."
                )
                safe_term = term.lower().replace(" ", "_").replace("-", "_")
                doc_id = f"term_{safe_term}"
                metadata = {
                    "type": "term",
                    "category": category,
                    "source": "initial_data",
                }

            elif doc_type == "supply_chain":
                from_co = entry.get("from", "")
                to_co = entry.get("to", "")
                relation = entry.get("relation", "")
                detail = entry.get("detail", "")
                doc_text = (
                    f"Supply chain: {from_co} -> {to_co} "
                    f"({relation}): {detail}"
                )
                doc_id = f"sc_{from_co.lower()}_{to_co.lower()}_{relation}"
                metadata = {
                    "type": "supply_chain",
                    "from": from_co,
                    "to": to_co,
                    "relation": relation,
                    "source": "initial_data",
                }

            else:
                return "", "", {}

            return doc_id, doc_text, metadata

        except Exception as exc:
            logger.warning(
                "문서 변환 실패 | type=%s | line=%d | error=%s",
                doc_type,
                line_num,
                exc,
            )
            return "", "", {}

    async def detect_unknown_terms(self, text: str) -> list[str]:
        """텍스트에서 미지용어를 감지한다.

        ChromaDB에서 검색하여 매칭되지 않는 전문 용어를 추출한다.

        Args:
            text: 분석할 텍스트.

        Returns:
            미지용어 리스트.
        """
        if not self._ensure_initialized():
            return []

        # 정규식으로 후보 용어 추출
        candidates = set(_TERM_PATTERN.findall(text))
        # 일반 약어 제거
        candidates -= _COMMON_ABBREVIATIONS
        # 2글자 이하 제거
        candidates = {t for t in candidates if len(t) > 2}

        if not candidates:
            return []

        unknown: list[str] = []
        for term in candidates:
            try:
                results = await asyncio.to_thread(
                    self._collection.query,
                    query_texts=[term],
                    n_results=1,
                )
                # 매칭 결과가 없거나 거리가 먼 경우 미지용어로 판단
                if (
                    not results["documents"]
                    or not results["documents"][0]
                    or not results["distances"]
                    or results["distances"][0][0] > 0.5
                ):
                    unknown.append(term)
            except Exception as exc:
                logger.warning(
                    "용어 검색 실패 | term=%s | error=%s", term, exc
                )
                unknown.append(term)

        if unknown:
            logger.info(
                "미지용어 감지: %d건 (후보 %d건 중)", len(unknown), len(candidates)
            )

        return unknown

    async def learn_term(self, term: str) -> dict[str, Any]:
        """Claude Opus로 미지용어 정의를 획득하고 DB에 저장한다.

        Args:
            term: 학습할 용어.

        Returns:
            {"term": str, "definition": str, "source": "claude_opus", "stored": bool}
        """
        if not self._ensure_initialized():
            return {
                "term": term,
                "definition": "",
                "source": "claude_opus",
                "stored": False,
            }

        logger.info("용어 학습 시작 | term=%s", term)
        start = time.monotonic()

        try:
            prompt = _TERM_DEFINITION_PROMPT.format(term=term)
            result = await self.claude_client.call_json(
                prompt=prompt,
                task_type="term_definition",
                max_tokens=512,
                use_cache=True,
            )

            if not isinstance(result, dict):
                logger.warning("Claude 응답이 딕셔너리가 아니다: %s", type(result))
                return {
                    "term": term,
                    "definition": "",
                    "source": "claude_opus",
                    "stored": False,
                }

            definition = str(result.get("definition", ""))
            category = str(result.get("category", "other"))
            related_terms = result.get("related_terms", [])
            if not isinstance(related_terms, list):
                related_terms = []

            # ChromaDB에 저장
            stored = await self._store_term(term, definition, category, related_terms)

            elapsed = time.monotonic() - start
            logger.info(
                "용어 학습 완료 | term=%s | stored=%s | elapsed=%.1fs",
                term,
                stored,
                elapsed,
            )

            return {
                "term": term,
                "definition": definition,
                "source": "claude_opus",
                "stored": stored,
            }

        except Exception as exc:
            logger.error("용어 학습 실패 | term=%s | error=%s", term, exc)
            return {
                "term": term,
                "definition": "",
                "source": "claude_opus",
                "stored": False,
            }

    async def _store_term(
        self,
        term: str,
        definition: str,
        category: str,
        related_terms: list[str],
    ) -> bool:
        """용어와 정의를 ChromaDB에 저장한다.

        bge-m3 임베더를 사용하여 벡터를 생성하고 저장한다.

        Args:
            term: 용어.
            definition: 정의 텍스트.
            category: 용어 카테고리.
            related_terms: 관련 용어 리스트.

        Returns:
            저장 성공 여부.
        """
        if not self._collection:
            return False

        try:
            doc_text = f"{term}: {definition}"
            embedding = self.embedder.encode_single(doc_text)

            # 고유 ID 생성 (용어 기반)
            doc_id = f"term_{term.lower().replace(' ', '_').replace('-', '_')}"

            await asyncio.to_thread(
                self._collection.upsert,
                ids=[doc_id],
                embeddings=[embedding],
                documents=[doc_text],
                metadatas=[{
                    "term": term,
                    "category": category,
                    "related_terms": ",".join(related_terms),
                    "source": "claude_opus",
                }],
            )
            return True
        except Exception as exc:
            logger.error("ChromaDB 저장 실패 | term=%s | error=%s", term, exc)
            return False

    async def search_knowledge(
        self, query: str, top_k: int = 5
    ) -> list[dict[str, Any]]:
        """지식 DB에서 관련 용어/정의를 검색한다.

        Args:
            query: 검색 쿼리.
            top_k: 반환할 최대 결과 수.

        Returns:
            검색 결과 리스트. 각 항목:
                - term: str
                - definition: str
                - category: str
                - similarity: float
        """
        if not self._ensure_initialized():
            return []

        try:
            embedding = self.embedder.encode_single(query)

            results = await asyncio.to_thread(
                self._collection.query,
                query_embeddings=[embedding],
                n_results=top_k,
            )

            docs: list[dict[str, Any]] = []
            if results["documents"] and results["documents"][0]:
                for i, doc_text in enumerate(results["documents"][0]):
                    metadata = (
                        results["metadatas"][0][i]
                        if results["metadatas"] and results["metadatas"][0]
                        else {}
                    )
                    distance = (
                        results["distances"][0][i]
                        if results["distances"] and results["distances"][0]
                        else 1.0
                    )
                    # ChromaDB cosine distance -> similarity
                    similarity = 1.0 - distance

                    docs.append({
                        "term": metadata.get("term", ""),
                        "definition": doc_text,
                        "category": metadata.get("category", "other"),
                        "similarity": round(similarity, 4),
                    })

            logger.debug(
                "지식 검색 완료 | query=%s | results=%d",
                query[:60],
                len(docs),
            )
            return docs

        except Exception as exc:
            logger.error("지식 검색 실패 | query=%s | error=%s", query[:60], exc)
            return []

    async def get_context_for_article(self, article: dict[str, Any]) -> str:
        """기사 분류 시 관련 지식 컨텍스트를 제공한다.

        기사의 제목과 요약에서 용어를 추출하고, 관련 지식을 검색하여
        분류 프롬프트에 추가할 컨텍스트 문자열을 생성한다.

        Args:
            article: 뉴스 기사 딕셔너리.

        Returns:
            분류 프롬프트에 추가할 컨텍스트 문자열. 관련 지식이 없으면 빈 문자열.
        """
        title = article.get("title", article.get("headline", ""))
        summary = article.get("summary", article.get("content", ""))
        query = f"{title} {summary}".strip()

        if not query:
            return ""

        docs = await self.search_knowledge(query, top_k=3)
        if not docs:
            return ""

        parts: list[str] = []
        for doc in docs:
            if doc["similarity"] >= 0.3:
                parts.append(
                    f"[{doc['category']}] {doc['term']}: {doc['definition']}"
                )

        if not parts:
            return ""

        context = "Relevant financial knowledge:\n" + "\n".join(parts)
        logger.debug(
            "기사 컨텍스트 생성 | terms=%d | article_title=%s",
            len(parts),
            title[:60],
        )
        return context

    def get_status(self) -> dict[str, Any]:
        """KnowledgeManager 상태 정보를 반환한다.

        Returns:
            상태 딕셔너리.
        """
        count = 0
        if self._collection is not None:
            try:
                count = self._collection.count()
            except Exception as exc:
                logger.debug("ChromaDB 문서 수 조회 실패: %s", exc)

        return {
            "chromadb_available": _CHROMADB_AVAILABLE,
            "initialized": self._initialized,
            "chroma_path": self._chroma_path,
            "collection_name": _COLLECTION_NAME,
            "document_count": count,
            "knowledge_dir": self.KNOWLEDGE_DIR,
        }

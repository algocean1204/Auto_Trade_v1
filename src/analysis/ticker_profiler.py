"""종목별 특징 프로필 생성기.

Claude Opus를 활용하여 종목의 핵심 특성을 분석하고,
RAG 문서로 저장하여 매매 판단 프롬프트에 주입한다.
"""

from __future__ import annotations

import json
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Claude 프롬프트 템플릿 — 종목 프로필 생성용 (Opus 사용)
# ---------------------------------------------------------------------------

TICKER_PROFILE_PROMPT = """You are a senior US stock market analyst with 20+ years of experience.
Analyze the following stock/ETF ticker and provide a comprehensive profile for an AI trading system.

Ticker: {ticker}
Name: {name}
Sector: {sector}
Underlying/Description: {underlying}

Write a detailed analysis in Korean covering these aspects. This profile will be used by an AI trading system to make better buy/sell decisions.

Return EXACTLY this JSON structure:
{{
  "ticker": "{ticker}",
  "core_characteristics": "핵심 특징 3-5줄 (예: 구글은 검색 독점, AI(제미나이), 양자컴 독자개발, 안드로이드/크롬 생태계, TPU로 엔비디아 의존도 낮음)",
  "competitive_advantages": ["경쟁 우위 1", "경쟁 우위 2", "경쟁 우위 3"],
  "risk_factors": ["리스크 1", "리스크 2", "리스크 3"],
  "price_characteristics": "주가 특성 (변동성 높음/낮음, 실적 시즌 반응, 금리 민감도 등)",
  "sector_dynamics": "해당 섹터 내 위치와 섹터 트렌드 영향도",
  "key_catalysts": ["주요 촉매 1 (예: AI 투자 확대)", "주요 촉매 2", "주요 촉매 3"],
  "correlation_notes": "다른 종목/지수와의 상관관계 (예: NVDA와 높은 상관, 금리와 역상관 등)",
  "trading_tips": "이 종목 매매 시 주의사항 (예: 실적 발표 전후 변동성 주의, 장 초반 갭 발생 빈번 등)",
  "historical_context": "최근 1-2년 주요 이벤트 및 주가 흐름 요약",
  "leverage_notes": "레버리지 ETF 사용 시 주의점 (해당되는 경우, 해당 없으면 빈 문자열)"
}}

IMPORTANT:
- Write ALL text values in Korean
- Be specific and actionable for trading decisions
- Focus on information that helps decide WHEN to buy/sell
- Include quantitative observations where possible
- Return ONLY valid JSON, no markdown, no explanation, no extra text
"""


class TickerProfiler:
    """종목 프로필을 Claude Opus로 생성하고 RAG DB에 저장한다.

    의존성:
        claude_client: ClaudeClient 인스턴스 (call_json 메서드 사용).
        rag_embedder: BGEEmbedder 인스턴스 (encode_single 메서드 사용, 선택).
    """

    def __init__(
        self,
        claude_client: Any,
        rag_embedder: Any | None = None,
    ) -> None:
        """TickerProfiler를 초기화한다.

        Args:
            claude_client: ClaudeClient 인스턴스.
            rag_embedder: BGEEmbedder 인스턴스 (None이면 임베딩 없이 저장).
        """
        self.claude = claude_client
        self.rag_embedder = rag_embedder

    async def generate_profile(
        self,
        ticker: str,
        name: str = "",
        sector: str = "",
        underlying: str = "",
    ) -> dict:
        """단일 종목의 프로필을 Claude Opus로 생성한다.

        Args:
            ticker: 종목 티커 심볼 (예: NVDA).
            name: 종목 전체 이름 (예: NVIDIA Corporation).
            sector: 섹터 (예: semiconductors).
            underlying: 기초 자산 설명 (예: Semiconductors / AI).

        Returns:
            프로필 딕셔너리. 실패 시 빈 딕셔너리.
        """
        prompt = TICKER_PROFILE_PROMPT.format(
            ticker=ticker,
            name=name or ticker,
            sector=sector or "N/A",
            underlying=underlying or name or ticker,
        )

        try:
            profile = await self.claude.call_json(
                prompt=prompt,
                task_type="trading_decision",  # Opus 라우팅
                max_tokens=4096,
                use_cache=False,
            )
        except Exception as exc:
            logger.error("Claude Opus 프로필 생성 실패 (%s): %s", ticker, exc)
            return {}

        if not isinstance(profile, dict):
            logger.error("프로필 응답이 딕셔너리가 아닙니다 (%s): %s", ticker, type(profile))
            return {}

        logger.info("프로필 생성 완료: %s", ticker)
        return profile

    async def save_to_rag(self, ticker: str, profile: dict) -> bool:
        """생성된 프로필을 RAG 문서(rag_documents 테이블)로 저장한다.

        기존 ticker_profile 문서가 있으면 먼저 삭제하고 새로 삽입한다.
        BGEEmbedder가 주입된 경우 임베딩을 생성하여 함께 저장한다.

        Args:
            ticker: 종목 티커 심볼.
            profile: generate_profile()이 반환한 프로필 딕셔너리.

        Returns:
            저장 성공 여부.
        """
        if not profile:
            logger.warning("빈 프로필 — RAG 저장 생략: %s", ticker)
            return False

        # 마크다운 형식의 content 문자열 구성
        content_parts: list[str] = [
            f"# {ticker} 종목 프로필",
            "",
            "## 핵심 특징",
            profile.get("core_characteristics", ""),
            "",
            "## 경쟁 우위",
        ]
        for adv in profile.get("competitive_advantages", []):
            content_parts.append(f"- {adv}")
        content_parts += [
            "",
            "## 리스크 요인",
        ]
        for risk in profile.get("risk_factors", []):
            content_parts.append(f"- {risk}")
        content_parts += [
            "",
            "## 주가 특성",
            profile.get("price_characteristics", ""),
            "",
            "## 섹터 내 위치",
            profile.get("sector_dynamics", ""),
            "",
            "## 주요 촉매",
        ]
        for cat in profile.get("key_catalysts", []):
            content_parts.append(f"- {cat}")
        content_parts += [
            "",
            "## 상관관계",
            profile.get("correlation_notes", ""),
            "",
            "## 매매 주의사항",
            profile.get("trading_tips", ""),
            "",
            "## 최근 히스토리",
            profile.get("historical_context", ""),
        ]
        leverage_notes = profile.get("leverage_notes", "")
        if leverage_notes:
            content_parts += [
                "",
                "## 레버리지 노트",
                leverage_notes,
            ]

        content = "\n".join(content_parts)
        title = f"{ticker} 종목 프로필"
        embed_text = f"{title}\n{content}"

        try:
            from src.db.connection import get_session
            from src.db.models import RagDocument
            from sqlalchemy import delete

            async with get_session() as session:
                # 기존 프로필 삭제
                await session.execute(
                    delete(RagDocument).where(
                        RagDocument.ticker == ticker,
                        RagDocument.doc_type == "ticker_profile",
                    )
                )

                # 임베딩 생성 (가능한 경우)
                embedding = None
                if self.rag_embedder is not None:
                    try:
                        embedding = self.rag_embedder.encode_single(embed_text)
                    except Exception as emb_exc:
                        logger.warning("임베딩 생성 실패 (%s): %s", ticker, emb_exc)

                doc = RagDocument(
                    doc_type="ticker_profile",
                    ticker=ticker,
                    title=title,
                    content=content,
                    source="claude_opus",
                    metadata_={"profile": profile, "generated_by": "TickerProfiler"},
                    relevance_score=1.0,
                )
                if embedding is not None:
                    doc.embedding = embedding

                session.add(doc)
                await session.commit()

            logger.info("RAG 프로필 저장 완료: %s", ticker)
            return True

        except Exception as exc:
            logger.error("RAG 프로필 저장 실패 (%s): %s", ticker, exc)
            return False

    async def generate_and_save(
        self,
        ticker: str,
        name: str = "",
        sector: str = "",
        underlying: str = "",
    ) -> dict:
        """프로필 생성 + RAG 저장을 한 번에 수행한다.

        Args:
            ticker: 종목 티커 심볼.
            name: 종목 이름.
            sector: 섹터.
            underlying: 기초 자산 설명.

        Returns:
            생성된 프로필 딕셔너리. 실패 시 빈 딕셔너리.
        """
        profile = await self.generate_profile(
            ticker=ticker,
            name=name,
            sector=sector,
            underlying=underlying,
        )
        if profile:
            await self.save_to_rag(ticker, profile)
        return profile

    async def generate_all_profiles(self, universe_manager: Any) -> dict:
        """모든 모니터링 종목의 프로필을 순차적으로 생성한다.

        Args:
            universe_manager: UniverseManager 인스턴스 (get_all_tickers 메서드 사용).

        Returns:
            {"success": [...], "failed": [...]} 형태의 결과 딕셔너리.
        """
        results: dict[str, list[str]] = {"success": [], "failed": []}

        try:
            all_tickers: dict = universe_manager.get_all_tickers()
        except Exception as exc:
            logger.error("유니버스 티커 목록 조회 실패: %s", exc)
            return results

        logger.info("전체 프로필 생성 시작: 총 %d 종목", len(all_tickers))

        for ticker, info in all_tickers.items():
            try:
                profile = await self.generate_and_save(
                    ticker=ticker,
                    name=info.get("name", ""),
                    sector=info.get("sector", ""),
                    underlying=info.get("underlying", ""),
                )
                if profile:
                    results["success"].append(ticker)
                else:
                    results["failed"].append(ticker)
            except Exception as exc:
                logger.error("프로필 생성 오류 (%s): %s", ticker, exc)
                results["failed"].append(ticker)

        logger.info(
            "전체 프로필 생성 완료: 성공=%d, 실패=%d",
            len(results["success"]),
            len(results["failed"]),
        )
        return results

    async def get_profile_from_rag(self, ticker: str) -> dict | None:
        """RAG DB에서 저장된 종목 프로필을 조회한다.

        Args:
            ticker: 종목 티커 심볼.

        Returns:
            프로필 딕셔너리 (id, title, content, metadata 포함). 없으면 None.
        """
        try:
            from src.db.connection import get_session
            from src.db.models import RagDocument
            from sqlalchemy import select

            async with get_session() as session:
                stmt = (
                    select(RagDocument)
                    .where(
                        RagDocument.ticker == ticker,
                        RagDocument.doc_type == "ticker_profile",
                    )
                    .order_by(RagDocument.created_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row is None:
                    return None
                return {
                    "id": str(row.id),
                    "ticker": row.ticker,
                    "title": row.title,
                    "content": row.content,
                    "metadata": row.metadata_,
                    "source": row.source,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
        except Exception as exc:
            logger.error("RAG 프로필 조회 실패 (%s): %s", ticker, exc)
            return None

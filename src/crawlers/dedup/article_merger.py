"""유사 기사 병합기 -- 제목 Jaccard 유사도 기반으로 같은 사건 기사를 합친다."""
from __future__ import annotations

from src.analysis.models import ClassifiedNews
from src.common.logger import get_logger

logger = get_logger(__name__)

# Jaccard 유사도 임계값 -- 이 이상이면 같은 사건으로 간주한다
_SIMILARITY_THRESHOLD: float = 0.4

# 제목 토큰화 시 제거할 불용어이다
_STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
    "to", "for", "of", "and", "or", "but", "with", "by", "from",
    "it", "its", "this", "that", "as", "be", "has", "have", "had",
}


def _tokenize(title: str) -> set[str]:
    """제목을 소문자 토큰 집합으로 변환한다. 불용어와 2글자 미만은 제거한다."""
    tokens = title.lower().split()
    return {t for t in tokens if t not in _STOP_WORDS and len(t) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    """두 집합의 Jaccard 유사도를 계산한다."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class ArticleMerger:
    """유사 기사를 제목 기반으로 병합한다."""

    def merge(self, articles: list[ClassifiedNews]) -> list[ClassifiedNews]:
        """유사도 >= 0.4인 기사를 그룹으로 묶고 대표 기사를 선정한다."""
        n = len(articles)
        if n <= 1:
            return articles

        # Union-Find 초기화
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # 토큰 사전 계산
        tokens = [_tokenize(a.title) for a in articles]

        # O(n^2) 쌍별 유사도 → Union-Find 병합
        for i in range(n):
            for j in range(i + 1, n):
                if _jaccard(tokens[i], tokens[j]) >= _SIMILARITY_THRESHOLD:
                    union(i, j)

        # 그룹 구성
        groups: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            groups.setdefault(root, []).append(i)

        # 각 그룹에서 impact_score 최고 기사를 대표로 선정한다
        merged: list[ClassifiedNews] = []
        for indices in groups.values():
            best_idx = max(indices, key=lambda i: articles[i].impact_score)
            representative = articles[best_idx]

            if len(indices) > 1:
                # 출처 병합 + 티커 합집합
                sources = list({articles[i].source for i in indices})
                all_tickers = list({
                    t for i in indices for t in articles[i].tickers_affected
                })
                source_tag = f"[출처 병합: {', '.join(sources)}]\n\n"
                representative = representative.model_copy(update={
                    "content": source_tag + representative.content,
                    "tickers_affected": all_tickers,
                })
            merged.append(representative)

        merged_count = n - len(merged)
        if merged_count > 0:
            logger.info("[Step 2.3] 유사 기사 병합: %d → %d건 (-%d)", n, len(merged), merged_count)
        return merged

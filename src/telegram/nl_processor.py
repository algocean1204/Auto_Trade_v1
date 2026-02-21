"""
텔레그램 자연어 처리 모듈.

슬래시 명령이 아닌 일반 텍스트 메시지를 Claude Sonnet으로 분석하여
적절한 명령/의도로 매핑한다.
"""

from __future__ import annotations

import re
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 의도 분류 프롬프트 템플릿
_INTENT_PROMPT = """사용자의 텔레그램 메시지를 분석하여 의도를 파악하라.

메시지: {message}

가능한 의도:
- status: 시스템 상태 조회 (예: "상태 알려줘", "시스템 어때?")
- positions: 포지션 조회 (예: "포지션 보여줘", "뭐 들고 있어?", "보유 종목")
- news: 뉴스 조회 (예: "뉴스 알려줘", "오늘 뉴스", "시장 소식")
- news_category: 카테고리별 뉴스 (예: "매크로 뉴스", "실적 뉴스") - params에 category 포함
- analyze: 특정 종목 분석 (예: "SOXL 어때?", "QQQ 분석해줘") - params에 ticker 포함
- report: 리포트 조회 (예: "오늘 실적", "리포트 보여줘")
- balance: 잔고 조회 (예: "잔고 얼마야", "돈 얼마 남았어")
- buy: 매수 요청 (예: "SOXL 500달러 매수", "TQQQ 사줘") - params에 ticker, amount 포함
- sell: 매도 요청 (예: "SOXL 전량 매도", "QLD 팔아줘") - params에 ticker, amount 포함
- stop: 거래 중단 (예: "매매 중단", "거래 멈춰")
- resume: 거래 재개 (예: "매매 재개", "다시 시작")
- help: 도움말 (예: "도움말", "뭐 할 수 있어?")
- chat: 일반 대화 (위 의도에 해당하지 않는 경우)

반드시 아래 JSON 형식으로만 응답하라:
{{"intent": "의도", "params": {{}}, "confidence": 0.0~1.0}}

params 예시:
- analyze: {{"ticker": "SOXL"}}
- news_category: {{"category": "macro"}}
- buy: {{"ticker": "SOXL", "amount": "500"}}
- sell: {{"ticker": "SOXL", "amount": "all"}}
- 나머지: {{}}"""


# 대화형 응답 프롬프트 템플릿
_CHAT_RESPONSE_PROMPT = """당신은 AI 주식 매매 시스템의 텔레그램 비서이다.
사용자 메시지에 친절하고 간결하게 한국어로 응답하라.

사용자 메시지: {message}

규칙:
- 간결하게 2-3문장으로 응답
- 텔레그램에서 읽기 좋게
- 주식/투자 관련 질문이면 가능한 도움이 되도록
- 명령어가 필요한 경우 적절한 명령어를 안내
- 불확실한 투자 조언은 하지 않음"""


class NLProcessor:
    """자연어 메시지를 의도로 분류하는 프로세서이다."""

    def __init__(self, claude_client: Any = None) -> None:
        """NLProcessor를 초기화한다.

        Args:
            claude_client: ClaudeClient 인스턴스. None이면 규칙 기반으로 폴백한다.
        """
        self._claude_client = claude_client

    def set_claude_client(self, claude_client: Any) -> None:
        """ClaudeClient 참조를 설정한다.

        Args:
            claude_client: ClaudeClient 인스턴스.
        """
        self._claude_client = claude_client

    async def classify_intent(self, message: str) -> dict[str, Any]:
        """메시지의 의도를 분류한다.

        Claude Sonnet을 사용하여 의도를 분류하고, 실패 시 규칙 기반 폴백을 사용한다.

        Args:
            message: 사용자 텍스트 메시지.

        Returns:
            {"intent": str, "params": dict, "confidence": float} 형태의 딕셔너리.
        """
        # 먼저 규칙 기반으로 빠르게 매칭 시도
        rule_result = self._rule_based_classify(message)
        if rule_result["confidence"] >= 0.9:
            return rule_result

        # Claude Sonnet으로 분류 시도
        if self._claude_client is not None:
            try:
                result = await self._claude_classify(message)
                if result["confidence"] >= 0.5:
                    return result
            except Exception as exc:
                logger.warning("Claude 의도 분류 실패, 규칙 기반 폴백: %s", exc)

        return rule_result

    async def generate_chat_response(self, message: str) -> str:
        """일반 대화 메시지에 대한 응답을 생성한다.

        Args:
            message: 사용자 텍스트 메시지.

        Returns:
            응답 문자열.
        """
        if self._claude_client is None:
            return (
                "자연어 처리 기능이 현재 비활성화되어 있습니다.\n"
                "/help 명령어로 사용 가능한 기능을 확인하세요."
            )

        try:
            prompt = _CHAT_RESPONSE_PROMPT.format(message=message)
            result = await self._claude_client.call(
                prompt=prompt,
                task_type="telegram_chat",
                max_tokens=300,
                temperature=0.7,
                use_cache=False,
            )
            return result.get("content", "응답을 생성할 수 없습니다.")
        except Exception as exc:
            logger.warning("대화 응답 생성 실패: %s", exc)
            return "잠시 후 다시 시도해 주세요."

    async def _claude_classify(self, message: str) -> dict[str, Any]:
        """Claude Sonnet으로 의도를 분류한다.

        Args:
            message: 사용자 텍스트 메시지.

        Returns:
            의도 분류 결과 딕셔너리.
        """
        prompt = _INTENT_PROMPT.format(message=message)
        result = await self._claude_client.call_json(
            prompt=prompt,
            task_type="telegram_intent",
            max_tokens=200,
            use_cache=False,
        )

        # 결과 정규화
        intent = result.get("intent", "chat")
        params = result.get("params", {})
        confidence = float(result.get("confidence", 0.5))

        logger.info(
            "NL 의도 분류: message=%s -> intent=%s (conf=%.2f)",
            message[:50], intent, confidence,
        )

        return {
            "intent": intent,
            "params": params,
            "confidence": confidence,
        }

    @staticmethod
    def _rule_based_classify(message: str) -> dict[str, Any]:
        """규칙 기반으로 의도를 분류한다.

        키워드 매칭으로 빠르게 의도를 파악한다.

        Args:
            message: 사용자 텍스트 메시지.

        Returns:
            의도 분류 결과 딕셔너리.
        """
        msg = message.strip().lower()

        # 상태
        if any(kw in msg for kw in ["상태", "시스템", "어때", "괜찮"]):
            return {"intent": "status", "params": {}, "confidence": 0.9}

        # 포지션
        if any(kw in msg for kw in ["포지션", "보유", "들고", "종목"]):
            return {"intent": "positions", "params": {}, "confidence": 0.9}

        # 뉴스 (카테고리 포함)
        categories = {
            "매크로": "macro", "macro": "macro",
            "실적": "earnings", "earnings": "earnings",
            "섹터": "sector", "sector": "sector",
            "정책": "policy", "policy": "policy",
            "지정학": "geopolitics", "geopolitics": "geopolitics",
            "기업": "company", "company": "company",
        }
        if any(kw in msg for kw in ["뉴스", "소식", "기사"]):
            for kr_cat, en_cat in categories.items():
                if kr_cat in msg:
                    return {
                        "intent": "news_category",
                        "params": {"category": en_cat},
                        "confidence": 0.95,
                    }
            return {"intent": "news", "params": {}, "confidence": 0.9}

        # 분석 (티커 추출 시도)
        if any(kw in msg for kw in ["분석", "어때", "차트", "rsi"]):
            ticker = _extract_ticker(msg)
            if ticker:
                return {
                    "intent": "analyze",
                    "params": {"ticker": ticker},
                    "confidence": 0.9,
                }

        # 리포트
        if any(kw in msg for kw in ["리포트", "보고서", "실적", "성과"]):
            return {"intent": "report", "params": {}, "confidence": 0.9}

        # 잔고
        if any(kw in msg for kw in ["잔고", "돈", "자산", "현금", "얼마"]):
            return {"intent": "balance", "params": {}, "confidence": 0.9}

        # 매수 ("사"는 너무 일반적이므로 제외, 티커+사줘 패턴만 허용)
        if any(kw in msg for kw in ["매수", "사줘", "사주", "buy"]):
            ticker = _extract_ticker(msg)
            amount = _extract_amount(msg)
            if ticker:
                return {
                    "intent": "buy",
                    "params": {"ticker": ticker, "amount": amount or "100"},
                    "confidence": 0.8,
                }

        # 매도 ("팔"은 "팔로우" 등과 겹칠 수 있으므로 "팔아"만 허용)
        if any(kw in msg for kw in ["매도", "팔아", "팔아줘", "sell"]):
            ticker = _extract_ticker(msg)
            amount = _extract_amount(msg) or "all"
            if ticker:
                return {
                    "intent": "sell",
                    "params": {"ticker": ticker, "amount": amount},
                    "confidence": 0.8,
                }

        # 중단
        if any(kw in msg for kw in ["중단", "멈춰", "스톱", "stop"]):
            return {"intent": "stop", "params": {}, "confidence": 0.9}

        # 재개
        if any(kw in msg for kw in ["재개", "시작", "resume"]):
            return {"intent": "resume", "params": {}, "confidence": 0.9}

        # 도움말
        if any(kw in msg for kw in ["도움", "help", "명령"]):
            return {"intent": "help", "params": {}, "confidence": 0.9}

        # 기본: 일반 대화
        return {"intent": "chat", "params": {}, "confidence": 0.3}


def _extract_ticker(text: str) -> str | None:
    """텍스트에서 미국 주식 티커를 추출한다.

    3-5글자 대문자 영어 단어를 티커 후보로 간주한다.

    Args:
        text: 검색 대상 텍스트.

    Returns:
        추출된 티커 문자열(대문자) 또는 None.
    """
    # 알려진 티커 목록 (2x 레버리지 ETF 중심)
    known_tickers = {
        "soxl", "soxs", "tqqq", "sqqq", "qld", "qid",
        "spxl", "spxs", "sso", "sds", "upro", "spxu",
        "tecl", "tecs", "fngu", "fngd", "labu", "labd",
        "nugt", "dust", "jnug", "jdst", "tna", "tza",
        "spy", "qqq", "iwm", "dia",
        "nvda", "aapl", "msft", "googl", "amzn", "meta", "tsla",
    }

    words = re.findall(r"[a-zA-Z]{2,5}", text)
    for word in words:
        if word.lower() in known_tickers:
            return word.upper()

    return None


def _extract_amount(text: str) -> str | None:
    """텍스트에서 금액 정보를 추출한다.

    "$500", "500달러", "500불", "all", "전량" 등을 인식한다.

    Args:
        text: 검색 대상 텍스트.

    Returns:
        추출된 금액 문자열 또는 None.
    """
    # "전량", "all", "전부" ("다"는 너무 일반적이므로 "다 팔아", "다 매도"만 허용)
    if any(kw in text.lower() for kw in ["전량", "all", "전부"]):
        return "all"
    # "다 팔아", "다 매도" 패턴만 허용
    if re.search(r"다\s*(팔|매도|sell)", text.lower()):
        return "all"

    # $숫자 또는 숫자달러/불
    patterns = [
        r"\$\s*([\d,]+(?:\.\d+)?)",
        r"([\d,]+(?:\.\d+)?)\s*(?:달러|불|dollar)",
        r"([\d,]+(?:\.\d+)?)\s*(?:만원|원)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).replace(",", "")

    # 단순 숫자 (3자리 이상)
    match = re.search(r"\b(\d{3,})\b", text)
    if match:
        return match.group(1)

    return None

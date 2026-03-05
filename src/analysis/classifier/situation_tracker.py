"""F2 AI 분석 -- 장기 지속 이슈의 경과를 추적하고 상황 보고서를 생성한다.

핵심뉴스(impact >= 0.7)를 Claude로 분석하여 전쟁/무역분쟁/금리사이클 등
진행 중인 상황을 감지하고, Redis에 타임라인을 관리한다.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone

from src.analysis.models import (
    KeyNews,
    OngoingSituation,
    SituationDetectionResult,
    SituationReport,
    SituationTimelineEntry,
)
from src.common.ai_gateway import AiClient
from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# Redis 키 패턴이다
_META_KEY = "situation:{id}:meta"
_TIMELINE_KEY = "situation:{id}:timeline"
_ACTIVE_IDS_KEY = "situation:active_ids"
_LAST_TELEGRAM_KEY = "situation:last_telegram_ts:{id}"

# TTL: 30일이다
_TTL: int = 30 * 24 * 3600

# 타임라인 최대 항목 수이다
_MAX_TIMELINE: int = 50

# 평가 프롬프트에 전달할 최근 타임라인 수이다
_RECENT_TIMELINE: int = 10

# 동일 상황 텔레그램 재전송 쿨다운(초)이다 — 1시간
_TELEGRAM_COOLDOWN: int = 3600

# 상태 한국어 매핑이다
_STATUS_KR: dict[str, str] = {
    "escalating": "악화 중",
    "stable": "안정",
    "de_escalating": "완화 중",
    "resolved": "해결됨",
}

_DETECTION_SYSTEM = (
    "너는 금융 뉴스 분석가이다. 주어진 핵심뉴스 목록에서 장기 지속 이슈"
    "(전쟁, 무역분쟁, 금리사이클, 정책변화 등)에 해당하는 뉴스를 식별하라."
)

_DETECTION_PROMPT = """아래는 최근 핵심뉴스 목록이다:
{news_block}

현재 추적 중인 활성 상황 ID: {active_ids}

위 뉴스 중 장기 지속 이슈에 해당하는 것을 식별하라.
기존 활성 상황에 매칭되면 해당 ID를 사용하고, 새로운 상황이면 새 ID를 생성하라.
ID 형식: 소문자 영문+숫자+언더스코어 (예: us_china_tariff_2026)

반드시 아래 JSON 배열 형식으로만 응답하라 (설명 없이):
[
  {{
    "situation_id": "...",
    "name": "한국어 이름",
    "category": "geopolitical|macro|policy",
    "status": "escalating|stable|de_escalating|resolved",
    "matched_news_titles": ["매칭된 뉴스 제목1", ...]
  }}
]

매칭되는 상황이 없으면 빈 배열 []을 반환하라."""

_ASSESSMENT_SYSTEM = (
    "너는 레버리지 ETF 전문 금융 분석가이다. "
    "진행 중인 상황의 타임라인을 분석하고 현재 평가를 작성하라."
)

_ASSESSMENT_PROMPT = """상황: {name} ({category})
현재 상태: {status}

기존 타임라인 (최근 {count}건):
{timeline_block}

새로 추가된 뉴스:
{new_entries_block}

위 타임라인과 새 뉴스를 종합하여 레버리지 ETF 투자 관점에서
한국어 2~3문장으로 현재 평가를 작성하라. 설명 없이 평가 문장만 출력하라."""


def _build_news_block(key_news: list[KeyNews]) -> str:
    """핵심뉴스 목록을 프롬프트용 텍스트 블록으로 변환한다."""
    lines: list[str] = []
    for i, n in enumerate(key_news, 1):
        lines.append(
            f"{i}. [{n.category}] {n.title} "
            f"(영향도: {n.impact_score:.1f}, {n.direction})"
        )
    return "\n".join(lines)


def _build_timeline_block(entries: list[SituationTimelineEntry]) -> str:
    """타임라인 항목을 프롬프트용 텍스트 블록으로 변환한다."""
    if not entries:
        return "(없음)"
    lines: list[str] = []
    for e in entries:
        ts = e.timestamp.strftime("%m/%d %H:%M")
        lines.append(f"- {ts} | {e.headline} ({e.source})")
    return "\n".join(lines)


def _parse_detection_response(content: str) -> list[SituationDetectionResult]:
    """Claude 감지 응답을 파싱한다. 실패 시 빈 리스트를 반환한다."""
    # JSON 배열 부분만 추출한다
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        raw_list = json.loads(content[start:end + 1])
    except json.JSONDecodeError:
        logger.warning("상황 감지 JSON 파싱 실패")
        return []

    results: list[SituationDetectionResult] = []
    for item in raw_list:
        try:
            results.append(SituationDetectionResult(**item))
        except Exception:
            logger.warning("상황 감지 항목 파싱 실패: %s", item)
    return results


def _esc(text: str) -> str:
    """텔레그램 HTML 특수문자를 이스케이프한다."""
    return html.escape(text, quote=False)


def format_situation_telegram(report: SituationReport) -> str:
    """상황 보고서를 HTML 메시지로 포맷팅한다."""
    status_kr = _STATUS_KR.get(report.status, report.status)
    lines: list[str] = [
        "━━━━━━━━━━━━━━━━━━━",
        f"<b>[진행 상황 보고] {_esc(report.name)}</b>",
        f"상태: {_esc(status_kr)} | 누적 기사 {report.full_timeline_count}건",
        "",
        "최근 업데이트:",
    ]
    for entry in report.new_entries[:5]:
        ts = entry.timestamp.strftime("%m/%d %H:%M")
        lines.append(f"  {ts} — {_esc(entry.headline)} ({_esc(entry.source)})")

    lines.append("")
    lines.append(f"현재 평가: {_esc(report.assessment)}")
    return "\n".join(lines)


class OngoingSituationTracker:
    """장기 지속 이슈의 경과를 추적하고 상황 보고서를 생성한다.

    CacheClient(Redis)에 타임라인을 누적하고,
    AiClient(Claude)로 상황 감지 및 평가를 수행한다.
    """

    def __init__(self, cache: CacheClient, ai: AiClient) -> None:
        self._cache = cache
        self._ai = ai
        logger.info("OngoingSituationTracker 초기화 완료")

    async def track(self, key_news: list[KeyNews]) -> list[SituationReport]:
        """핵심뉴스에서 진행 상황을 감지하고 보고서를 생성한다."""
        if not key_news:
            return []

        # 1) Claude 배치 호출: 상황 감지
        detections = await self._detect_situations(key_news)
        if not detections:
            logger.info("[Step 2.8] 진행 상황 감지 결과 없음")
            return []

        # 2) 각 감지된 상황별 타임라인 업데이트 + 평가 생성
        reports: list[SituationReport] = []
        for detection in detections:
            try:
                report = await self._process_situation(detection, key_news)
                if report is not None:
                    reports.append(report)
            except Exception as exc:
                logger.warning(
                    "[Step 2.8] 상황 처리 실패 (%s): %s",
                    detection.situation_id, exc,
                )

        logger.info("[Step 2.8] 진행 상황 보고서 생성: %d건", len(reports))
        return reports

    async def _detect_situations(
        self, key_news: list[KeyNews],
    ) -> list[SituationDetectionResult]:
        """Claude로 핵심뉴스에서 진행 상황을 감지한다."""
        try:
            active_ids = await self._load_active_ids()
            news_block = _build_news_block(key_news)
            prompt = _DETECTION_PROMPT.format(
                news_block=news_block,
                active_ids=", ".join(active_ids) if active_ids else "(없음)",
            )
            response = await self._ai.send_text(
                prompt=prompt,
                system=_DETECTION_SYSTEM,
                model="sonnet",
                max_tokens=2048,
            )
            return _parse_detection_response(response.content)
        except Exception as exc:
            logger.warning("[Step 2.8] Claude 상황 감지 호출 실패: %s", exc)
            return []

    async def _process_situation(
        self,
        detection: SituationDetectionResult,
        key_news: list[KeyNews],
    ) -> SituationReport | None:
        """단일 상황을 처리한다: 타임라인 업데이트 + 평가 생성."""
        sid = detection.situation_id
        now = datetime.now(timezone.utc)

        # 텔레그램 중복 전송 방지 — 쿨다운 이내이면 타임라인만 업데이트하고 보고서는 생성하지 않는다
        recently_sent = await self._is_recently_sent(sid)

        # 기존 메타데이터/타임라인 로드
        meta = await self._load_meta(sid)
        timeline = await self._load_timeline(sid)

        # 매칭된 뉴스를 타임라인 항목으로 변환
        matched_titles = set(detection.matched_news_titles)
        new_entries: list[SituationTimelineEntry] = []
        for n in key_news:
            if n.title in matched_titles:
                new_entries.append(SituationTimelineEntry(
                    timestamp=now,
                    headline=n.title,
                    summary=n.summary,
                    source=n.source or n.category,
                ))

        if not new_entries:
            return None

        # 타임라인에 추가 (최대 _MAX_TIMELINE건 유지)
        timeline.extend(new_entries)
        if len(timeline) > _MAX_TIMELINE:
            timeline = timeline[-_MAX_TIMELINE:]

        # 메타데이터 갱신
        if meta is None:
            meta = OngoingSituation(
                situation_id=sid,
                name=detection.name,
                category=detection.category,
                status=detection.status,
                first_seen=now,
                last_updated=now,
                article_count=len(new_entries),
            )
        else:
            meta.status = detection.status
            meta.last_updated = now
            meta.article_count += len(new_entries)

        # Redis 저장 (타임라인/메타는 항상 업데이트한다)
        await self._save_meta(sid, meta)
        await self._save_timeline(sid, timeline)

        # resolved 상황은 active_ids에서 제거, 그 외는 추가한다
        if detection.status == "resolved":
            await self._remove_from_active_ids(sid)
        else:
            await self._update_active_ids(sid)

        # 쿨다운 이내이면 보고서 생성을 건너뛴다 (타임라인은 이미 저장됨)
        if recently_sent:
            logger.debug(
                "[Step 2.8] 쿨다운 이내 — 보고서 생략: %s", sid,
            )
            return None

        # Claude 평가 생성
        assessment = await self._generate_assessment(
            meta, timeline, new_entries,
        )

        # 텔레그램 전송 시각을 기록한다
        await self._mark_telegram_sent(sid)

        return SituationReport(
            situation_id=sid,
            name=meta.name,
            status=meta.status,
            new_entries=new_entries,
            full_timeline_count=len(timeline),
            assessment=assessment,
        )

    async def _generate_assessment(
        self,
        meta: OngoingSituation,
        timeline: list[SituationTimelineEntry],
        new_entries: list[SituationTimelineEntry],
    ) -> str:
        """Claude로 현재 평가를 생성한다."""
        try:
            recent = timeline[-_RECENT_TIMELINE:]
            prompt = _ASSESSMENT_PROMPT.format(
                name=meta.name,
                category=meta.category,
                status=meta.status,
                count=len(recent),
                timeline_block=_build_timeline_block(recent),
                new_entries_block=_build_timeline_block(new_entries),
            )
            response = await self._ai.send_text(
                prompt=prompt,
                system=_ASSESSMENT_SYSTEM,
                model="sonnet",
                max_tokens=512,
            )
            return response.content.strip()
        except Exception as exc:
            logger.warning("[Step 2.8] Claude 평가 생성 실패: %s", exc)
            return "평가 생성 실패"

    # -- Redis 조작 메서드 --

    async def _load_active_ids(self) -> list[str]:
        """활성 상황 ID 목록을 로드한다."""
        try:
            data = await self._cache.read_json(_ACTIVE_IDS_KEY)
            if isinstance(data, list):
                return data
        except Exception as exc:
            logger.warning("활성 ID 로드 실패: %s", exc)
        return []

    async def _update_active_ids(self, sid: str) -> None:
        """활성 상황 ID 목록에 추가한다."""
        try:
            ids = await self._load_active_ids()
            if sid not in ids:
                ids.append(sid)
            await self._cache.write_json(_ACTIVE_IDS_KEY, ids, ttl=_TTL)
        except Exception:
            logger.exception("활성 ID 갱신 실패: %s", sid)

    async def _remove_from_active_ids(self, sid: str) -> None:
        """resolved 상황을 활성 ID 목록에서 제거한다."""
        try:
            ids = await self._load_active_ids()
            if sid in ids:
                ids.remove(sid)
                await self._cache.write_json(_ACTIVE_IDS_KEY, ids, ttl=_TTL)
                logger.info("resolved 상황 active_ids에서 제거: %s", sid)
        except Exception:
            logger.exception("활성 ID 제거 실패: %s", sid)

    async def _is_recently_sent(self, sid: str) -> bool:
        """쿨다운 이내에 텔레그램 전송 이력이 있는지 확인한다."""
        try:
            key = _LAST_TELEGRAM_KEY.format(id=sid)
            raw = await self._cache.read(key)
            if raw is None:
                return False
            last_ts = datetime.fromisoformat(raw)
            elapsed = (datetime.now(timezone.utc) - last_ts).total_seconds()
            return elapsed < _TELEGRAM_COOLDOWN
        except Exception as exc:
            logger.warning("텔레그램 전송 이력 확인 실패 (%s): %s", sid, exc)
            return False

    async def _mark_telegram_sent(self, sid: str) -> None:
        """텔레그램 전송 시각을 Redis에 기록한다."""
        try:
            key = _LAST_TELEGRAM_KEY.format(id=sid)
            now_iso = datetime.now(timezone.utc).isoformat()
            await self._cache.write(key, now_iso, ttl=_TTL)
        except Exception:
            logger.exception("텔레그램 전송 시각 기록 실패: %s", sid)

    async def _load_meta(self, sid: str) -> OngoingSituation | None:
        """Redis에서 상황 메타데이터를 로드한다."""
        try:
            key = _META_KEY.format(id=sid)
            data = await self._cache.read_json(key)
            if data and isinstance(data, dict):
                return OngoingSituation(**data)
        except Exception:
            logger.warning("상황 메타 로드 실패: %s", sid)
        return None

    async def _save_meta(self, sid: str, meta: OngoingSituation) -> None:
        """Redis에 상황 메타데이터를 저장한다."""
        try:
            key = _META_KEY.format(id=sid)
            await self._cache.write_json(key, meta.model_dump(), ttl=_TTL)
        except Exception:
            logger.exception("상황 메타 저장 실패: %s", sid)

    async def _load_timeline(self, sid: str) -> list[SituationTimelineEntry]:
        """Redis에서 타임라인을 로드한다."""
        try:
            key = _TIMELINE_KEY.format(id=sid)
            data = await self._cache.read_json(key)
            if data and isinstance(data, list):
                return [SituationTimelineEntry(**item) for item in data]
        except Exception:
            logger.warning("타임라인 로드 실패: %s", sid)
        return []

    async def _save_timeline(
        self, sid: str, timeline: list[SituationTimelineEntry],
    ) -> None:
        """Redis에 타임라인을 저장한다."""
        try:
            key = _TIMELINE_KEY.format(id=sid)
            data = [e.model_dump() for e in timeline]
            await self._cache.write_json(key, data, ttl=_TTL)
        except Exception:
            logger.exception("타임라인 저장 실패: %s", sid)

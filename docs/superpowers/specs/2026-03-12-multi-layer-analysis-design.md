# 다계층 분석 아키텍처 설계서

## 목표

현재 Sonnet 5개 순차 실행 구조를 **센티넬(2분) + 정밀분석(60분)** 이중 루프 아키텍처로 교체한다.
로컬 AI + 룰 기반 센티넬로 긴급 대응 속도를 높이고, Opus 3+1 팀으로 최종 판단 품질을 높인다.

## 계층 구조

```
Layer 0: 센티넬 (2분, 비용 0)
  ├── 룰 기반: 가격/VIX/거래량/포지션 임계값 체크
  └── 로컬 AI: Qwen2.5 단일 모델 헤드라인 긴급도 분류
         ↓ urgent/watch 감지 시
Layer 0.5: Sonnet 평가 (조건부, 저비용)
  └── "이 이상 신호가 매매 행동이 필요한 수준인가?"
         ↓ emergency 판정 시
  └── Opus 1명 즉시 긴급 판단

Layer 1: Sonnet 4에이전트 병렬 분석 (60분 주기)
  ├── 뉴스 분석가 (NEWS_ANALYST)
  ├── 매크로 전략가 (MACRO_STRATEGIST)
  ├── 리스크 매니저 (RISK_MANAGER)
  └── 단기 트레이더 (SHORT_TERM_TRADER)
         ↓
Layer 2: Opus 3+1 팀 최종 판단 (60분 주기)
  ├── 공격형 분석가 (독립)
  ├── 균형형 분석가 (독립)
  ├── 보수형 분석가 (독립, 병렬)
  └── 리더 (3의견 종합, 순차)
```

## 모듈 구조

```
src/analysis/sentinel/
  ├── __init__.py
  ├── models.py           ← AnomalyResult, EscalationResult
  ├── anomaly_detector.py ← 룰 기반 + 로컬 AI 이상 감지
  └── escalation.py       ← Sonnet 평가 + Opus 긴급 판단

src/analysis/team/
  ├── comprehensive_team.py ← 수정: 4에이전트 병렬
  └── opus_judgment.py      ← 신규: Opus 3+1 최종 판단

src/orchestration/loops/
  ├── sentinel_loop.py      ← 신규: 2분 센티넬 루프
  └── continuous_analysis.py ← 수정: 60분 + 센티넬 연동
```

## 룰 기반 센티넬 상세

### 가격 급변 감지
- 입력: broker.virtual_client.get_current_price(ticker)
- 기준: |change_pct| >= 2.0%
- 보유 포지션 티커 + 감시 ETF(SPY, QQQ) 대상
- 엣지: 프리마켓 가격 데이터 없으면 스킵 (트리거 안 함)

### VIX 급변 감지
- 입력: vix_fetcher.get_vix() + Redis "sentinel:vix_prev" 이전값
- 기준: |현재 - 이전| >= 3.0pt
- 엣지: FRED API 실패 → 캐시된 이전값 사용, 이전값 없으면 스킵
- 엣지: 첫 실행 시 이전값 없음 → 현재값 저장만 하고 스킵

### 거래량 급증 감지
- 입력: PriceData.volume / avg_volume
- 기준: volume >= avg_volume * 3.0 (300%)
- 엣지: avg_volume=0이면 스킵 (ZeroDivision 방지)
- 엣지: 프리마켓 거래량은 정규장 대비 낮으므로 세션별 배수 조정 필요 없음 (절대 기준)

### 포지션 위험 근접 감지
- 입력: position_monitor.get_all_positions()
- 하드스톱 근접: pnl_pct <= -0.7% (하드스톱 -1.0%의 70% 지점)
- 수익목표 근접: pnl_pct >= take_profit * 0.8 (목표의 80% 도달)
- 엣지: 포지션 없으면 스킵

### 로컬 AI 뉴스 스캔
- 입력: fast_mode 크롤링 → 신규 헤드라인 title 목록
- 분류: Qwen2.5 단일 모델 (앙상블 아님, 속도 우선)
- 카테고리: ["urgent", "watch", "normal"]
- urgent → 즉시 에스컬레이션
- watch → Redis sentinel:watch에 저장, 다음 정기 분석에 포함

## Opus 토큰 사용량 추정

8시간 세션 (23:00~07:00):
- 정기 분석 8회 × Opus 4회 = 32회
- 긴급 호출 평균 3회 = 3회
- 총합 ~35 Opus 호출
- Pro 5시간 ~45회 기준: ~78% 사용

## 기존 호환성

- ComprehensiveReport 모델 변경 없음
- DecisionMaker 변경 없음
- TradingLoop의 보고서 소비 방식 변경 없음
- Redis 키 구조 기존 유지 + sentinel:* 추가

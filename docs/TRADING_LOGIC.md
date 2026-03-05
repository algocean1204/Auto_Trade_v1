# AI Auto-Trading System V2 - 매매 전략

## 개요

이 문서는 AI 자동매매 시스템의 매매 전략, AI 프롬프트, 의사결정 플로우, 안전 메커니즘을 설명한다.

## 매매 전략 개요

### 대상 자산

미국 2X/3X 레버리지 ETF를 대상으로 단기 트레이딩을 수행한다.

### 17종 본주-레버리지 ETF 매핑

| 본주 | Bull (2X Long) | Bear (2X Inverse) | 섹터 |
|------|----------------|-------------------|------|
| SPY | SSO | SDS | S&P 500 |
| QQQ | QLD | QID | NASDAQ 100 |
| SOXX | USD | SSG | 반도체 |
| IWM | UWM | TWM | Russell 2000 |
| DIA | DDM | DXD | Dow Jones |
| XLK | ROM | REW | 기술 |
| XLF | UYG | SKF | 금융 |
| XLE | DIG | DUG | 에너지 |
| TSLA | TSLL | TSLS | 테슬라 |
| NVDA | NVDL | NVDS | 엔비디아 |
| AAPL | AAPB | AAPD | 애플 |
| AMZN | AMZU | AMZD | 아마존 |
| META | METU | - | 메타 |
| GOOGL | GGLL | - | 구글 |
| MSFT | MSFL | - | 마이크로소프트 |
| AMD | AMDU | - | AMD |
| COIN | CONL | - | 코인베이스 |

**분석-실행 분리 원칙:**
- 기술적 지표 분석은 본주(underlying) 데이터를 사용한다
- 실제 주문은 레버리지 ETF 티커로 실행한다
- `ticker_mapping.py`의 `get_analysis_ticker()`로 자동 매핑한다

## AI 시스템 프롬프트

### 1. MASTER_ANALYST (매매 결정)

Claude Opus가 사용하는 핵심 페르소나이다.

**정체성:**
- 20년+ 월스트리트 경력의 시니어 포트폴리오 매니저
- 미국 2X/3X 레버리지 ETF 단기 트레이딩 전문가
- 연평균 40%+ 수익률 달성 탑티어 트레이더

**5단계 분석 프레임워크:**
1. **매크로 환경 (Dalio 방식)**: 금리 사이클, 유동성, 달러, 경기 순환, 지정학 리스크
2. **시장 심리 (Soros 방식)**: 반사성, crowded trade 감지, 공포/탐욕 해석
3. **확신 기반 포지셔닝 (Druckenmiller 방식)**: 비대칭 수익, 과감 vs 현금
4. **정량 분석 (Simons 방식)**: 기술적 지표, 가격 패턴, 변동성 클러스터링
5. **리스크 관리 (Paul Tudor Jones 방식)**: 출구 먼저 정하기, 테일 리스크

**매매 원칙 (불변):**
1. 뉴스가 최우선이다
2. 섹터 로테이션을 읽어라
3. FOMC/CPI/고용지표 전후는 전쟁이다
4. 갭(Gap)은 정보이다
5. 손절은 종교이다
6. 과매수 구간 추격 매수 금지
7. 현금도 포지션이다
8. 실적 시즌 리스크 축소
9. 야간 리스크 최소화

### 2. NEWS_ANALYST (뉴스 분류)

Claude Sonnet이 뉴스를 분류하는 프롬프트이다.

**분류 체계:**
- 카테고리: macro / earnings / company / sector / policy / geopolitics
- 영향도: high / medium / low
- 방향: bullish / bearish / neutral
- 관련 티커 추출

### 3. RISK_MANAGER (리스크 평가)

리스크 관점에서 포지션을 평가하는 프롬프트이다.

**평가 항목:**
- 포트폴리오 집중도 리스크
- VIX 수준 기반 리스크 조절
- 연속 손실 대응 전략
- 테일 리스크 시나리오

### 4. MACRO_STRATEGIST (거시경제 분석)

거시경제 환경을 분석하여 전략 방향을 제시하는 프롬프트이다.

**분석 대상:**
- Federal Funds Rate, 10Y-2Y Spread
- VIX, Consumer Price Index
- 고용률, 국채 수익률
- FOMC 캘린더, 경제 이벤트

## 의사결정 플로우

### 매매 루프 (15분 주기)

```
[1] Delta Crawl (새 뉴스 수집)
     │
     v
[2] 뉴스 분류 (Sonnet/MLX)
     ├── category, impact, direction 판정
     └── 고영향 뉴스 → Telegram 알림
     │
     v
[3] AI Context Build
     ├── 최근 뉴스 요약
     ├── 현재 포지션 상태
     ├── 기술적 지표 (RSI, MACD, Bollinger)
     ├── 시장 레짐 (bull/bear/neutral)
     ├── VIX 수준
     ├── Fear & Greed 지수
     └── RAG 관련 문서 검색
     │
     v
[4] DecisionMaker (Claude Opus)
     ├── MASTER_ANALYST 페르소나로 분석
     ├── 전체 컨텍스트 종합 판단
     └── JSON 형식으로 결정 출력
         {
           "action": "BUY|SELL|HOLD|REDUCE",
           "ticker": "SOXL",
           "confidence": 0.85,
           "size_pct": 10.0,
           "reason": "반도체 섹터 강세...",
           "stop_loss": -2.0,
           "take_profit": 3.0
         }
     │
     v
[5] Safety Chain 통과 검증
     ├── HardSafety: VIX < 35, 일일 손실 < 5%
     ├── SafetyChecker: 종합 등급 확인
     ├── EmergencyProtocol: 서킷브레이커 미발동
     ├── CapitalGuard: 잔고 충분, 주문 적정
     └── RiskGate: 6개 게이트 전부 PASS
     │
     v (PASS)
[6] OrderManager → KIS API 주문 실행
     ├── 시장가 / 지정가 주문
     ├── 슬리피지 추적
     └── 체결 확인
     │
     v
[7] PositionMonitor (실시간 추적)
     ├── Take Profit 도달 → 자동 청산
     ├── Stop Loss 도달 → 자동 청산
     ├── Trailing Stop → 수익 확보 후 청산
     └── 3일+ 보유 → ForcedLiquidator
```

## 생존 매매 모드

### 핵심 원칙

매월 최소 $300의 운영비(Claude API)를 수익으로 충당해야 한다.
이를 달성하지 못하면 시스템은 폐기된다.

### 생존 매매 규칙

1. **월 최소 $300 수익 달성이 존재의 이유이다**
2. **원금 보존이 수익보다 중요하다**
3. **확실한 기회에만 진입한다**
4. **손절은 생존의 핵심이다**
5. **월간 목표 달성 상황에 따라 리스크를 조절한다:**
   - 목표 미달: 보수적, 확실한 기회만, 포지션 축소
   - 목표 달성: 정상 매매, 무리하지 않음
   - 목표 초과: 여유분으로 공격적 탐색 가능
6. **연속 손실 시 즉시 매매 중단하고 관망한다**
7. **매매 전 자문: "이 매매가 실패하면 내 생존에 영향을 주는가?"**

### strategy_params.json

```json
{
  "take_profit_pct": 3.0,
  "trailing_stop_pct": 1.5,
  "stop_loss_pct": -2.0,
  "eod_close": true,
  "min_confidence": 0.7,
  "max_position_pct": 15.0,
  "max_total_position_pct": 80.0,
  "max_daily_trades": 30,
  "max_daily_loss_pct": -5.0,
  "max_hold_days": 5,
  "vix_shutdown_threshold": 35,
  "survival_trading": {
    "monthly_cost_usd": 300,
    "monthly_target_usd": 500,
    "enabled": true
  }
}
```

| 파라미터 | 값 | 설명 |
|----------|-----|------|
| take_profit_pct | 3.0% | 익절 목표 |
| trailing_stop_pct | 1.5% | 추적 손절 폭 |
| stop_loss_pct | -2.0% | 손절 한도 |
| eod_close | true | 장 마감 시 포지션 청산 |
| min_confidence | 0.7 | AI 최소 신뢰도 |
| max_position_pct | 15.0% | 단일 종목 최대 비중 |
| max_total_position_pct | 80.0% | 전체 포지션 최대 비중 |
| max_daily_trades | 30 | 일일 최대 거래 수 |
| max_daily_loss_pct | -5.0% | 일일 최대 손실 |
| max_hold_days | 5 | 최대 보유 일수 |
| vix_shutdown_threshold | 35 | VIX 셧다운 임계값 |

## 연속 분석 루프

### 스케줄 (23:00~06:30 KST)

```
23:00  Pre-market 준비
       ├── 인프라 점검 (DB, Redis, KIS)
       ├── Full Crawling (30개 소스)
       ├── 뉴스 분류 (Sonnet 배치)
       ├── 시장 분석 (Opus)
       └── Safety Check

00:00  Regular Market 시작
 ~     ├── 15분 주기 매매 루프
06:00  └── Delta Crawl → Classify → Decide → Execute → Monitor

06:00  EOD 정리
 ~     ├── Overnight Judge (보유 포지션 판단)
06:30  ├── Daily Feedback (매매 분석)
       ├── Forced Liquidation (3일+ 보유)
       └── Cleanup (카운터 리셋)

일요일  Weekly Analysis (주간 성과 분석, 파라미터 조정 제안)
```

## Triple RSI 전략

### 3중 RSI + Signal

세 가지 기간의 RSI를 동시에 분석하여 진입/청산 신호를 생성한다.

| RSI | 기간 | 용도 |
|-----|------|------|
| RSI(7) | 단기 | 단기 과매수/과매도 감지 |
| RSI(14) | 중기 | 표준 RSI, Signal(9) 크로스 |
| RSI(21) | 장기 | 추세 확인 |

**Signal Line:** RSI(14)의 9일 EMA

**진입 신호:**
- RSI(7) < 30 + RSI(14) Signal 골든크로스 → 강한 매수
- RSI(14) < 40 + RSI(21) 상승 추세 → 매수

**청산 신호:**
- RSI(7) > 70 + RSI(14) Signal 데드크로스 → 매도
- RSI(14) > 80 → 과매수 구간, 추격 매수 금지

**본주-레버리지 분리:**
- RSI 계산은 본주(SPY, QQQ, NVDA 등)의 가격 데이터를 사용한다
- 레버리지 ETF의 자체 RSI는 왜곡이 심하므로 사용하지 않는다

## 시장 레짐 감지

### RegimeDetector

VIX와 기술적 지표를 기반으로 시장 레짐을 감지한다.

| 레짐 | 조건 | 전략 |
|------|------|------|
| strong_bull | VIX < 15, 지표 강세 | 공격적 매수, 포지션 확대 |
| mild_bull | VIX 15~20, 지표 약세 | 선별적 매수 |
| neutral | VIX 20~25 | 현금 비중 확대, 관망 |
| mild_bear | VIX 25~30 | 방어적, 소규모 포지션 |
| strong_bear | VIX 30~35 | 최소 포지션, 현금 위주 |
| crisis | VIX 35+ | 전체 매매 중단 (HardSafety) |

## 안전 메커니즘 (5단계 체인)

### Layer 1: HardSafety (절대 한도)

무조건 차단하는 최상위 안전 장치이다.

- **VIX >= 35**: 전체 매매 즉시 중단
- **일일 손실 >= 5%**: 당일 신규 주문 차단
- **포지션 한도 초과**: max_position_pct(15%) 초과 시 차단
- **시장 외 시간**: 미국 장 외 시간 주문 차단

### Layer 2: SafetyChecker (종합 점검)

포트폴리오 건전성을 종합 평가한다.

- 안전 등급: A(정상) / B(주의) / C(위험) / D(긴급)
- Claude API 할당량 확인
- 연속 손실 횟수 체크

### Layer 3: EmergencyProtocol (긴급 프로토콜)

급격한 시장 변동에 대응한다.

- **서킷브레이커**: 급격한 가격 변동 시 매매 일시 중단
- **Flash Crash 감지**: 개별 종목 급락 시 해당 종목 쿨다운
- **Runaway Loss**: 연속 대규모 손실 시 전체 포지션 청산
- **쿨다운 타이머**: 발동 후 일정 시간 매매 금지

### Layer 4: CapitalGuard (자본금 보호)

주문 실행 직전 자본금 안전을 3중 검증한다.

- **Safety 3-Set**: 잔고 확인 → 주문 검증 → 체결 확인
- **잔고 충분성**: 주문 금액 대비 가용 잔고
- **주문 적정성**: 주문 크기가 파라미터 범위 내인지

### Layer 5: RiskGatePipeline (6개 리스크 게이트)

세분화된 리스크를 개별 게이트로 관리한다.

| 게이트 | 기능 |
|--------|------|
| DailyLossLimiter | 일일 손실 한도 (-5%) |
| ConcentrationLimiter | 단일 종목 집중도 15% 제한 |
| LosingStreakDetector | 연속 3회 손실 시 포지션 50% 축소 |
| SimpleVaR | VaR 기반 최대 포지션 크기 계산 |
| RiskBudget | 일일 리스크 예산 관리 |
| TrailingStopLoss | 수익 발생 후 추적 손절 |

## 피드백 루프

### Daily Feedback

매일 장 마감 후 Claude Opus가 당일 매매를 분석한다.

- 성공/실패 패턴 식별
- 지표별 진입 성과 분석
- 개선사항 제안
- DB에 feedback_reports 저장

### Weekly Analysis

매주 일요일 주간 성과를 심층 분석한다.

- 주간 수익률, 승률, 드로다운
- 파라미터 조정 제안 (pending_adjustments)
- 사용자 승인 후 적용

### ParamAdjuster

피드백 결과를 기반으로 전략 파라미터 조정을 제안한다.

- 현재값, 제안값, 변경 사유를 DB에 저장
- 사용자가 대시보드에서 승인/거부
- 승인 시 strategy_params.json에 자동 반영

### RAG Document Update

매매 결과와 시장 분석을 RAG 문서로 자동 변환하여 저장한다.
향후 AI 분석 시 관련 문서를 검색하여 컨텍스트에 포함한다.

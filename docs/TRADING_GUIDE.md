# 매매 시스템 운용 가이드

이 문서는 AI 자동매매 시스템 V2의 매매 운용, 리스크 관리, 자동화 설정, 대시보드 활용 방법을 설명한다.

---

## 목차

1. [지원 종목](#1-지원-종목)
2. [매매 전략 개요](#2-매매-전략-개요)
3. [전략 파라미터](#3-전략-파라미터)
4. [리스크 관리](#4-리스크-관리)
5. [시장 시간 및 세션](#5-시장-시간-및-세션)
6. [LaunchAgent 자동화](#6-launchagent-자동화)
7. [Telegram 봇 운용](#7-telegram-봇-운용)
8. [대시보드 활용](#8-대시보드-활용)
9. [수익 목표 관리](#9-수익-목표-관리)
10. [모의투자에서 실전 전환](#10-모의투자에서-실전-전환)
11. [긴급 상황 대응](#11-긴급-상황-대응)
12. [일일/주간 운용 체크리스트](#12-운용-체크리스트)

---

## 1. 지원 종목

### 본주-레버리지 ETF 매핑 (17쌍)

시스템은 본주(underlying) 데이터로 기술적 분석을 수행하고, 실제 주문은 레버리지 ETF로 실행한다.

#### 지수 ETF

| 본주 | Bull 2X | Bear 2X | 설명 |
|------|---------|---------|------|
| SPY | SSO | SDS | S&P 500 |
| QQQ | QLD | QID | NASDAQ 100 |
| SOXX | USD | SSG | 반도체 지수 |
| IWM | UWM | TWM | Russell 2000 |
| DIA | DDM | DXD | Dow Jones |
| XLK | ROM | REW | 기술 섹터 |
| XLF | UYG | SKF | 금융 섹터 |
| XLE | DIG | DUG | 에너지 섹터 |

#### 개별 주식 레버리지

| 본주 | Bull 2X | Bear 2X | 설명 |
|------|---------|---------|------|
| TSLA | TSLL | TSLS | 테슬라 |
| NVDA | NVDL | NVDS | 엔비디아 |
| AAPL | AAPB | AAPD | 애플 |
| AMZN | AMZU | AMZD | 아마존 |
| META | METU | - | 메타 |
| GOOGL | GGLL | - | 구글 |
| MSFT | MSFL | - | 마이크로소프트 |
| AMD | AMDU | - | AMD |
| COIN | CONL | - | 코인베이스 |
| MSTR | MSTU | MSTZ | 마이크로스트래티지 |

### 섹터별 분류

시스템은 종목을 12개 섹터로 분류하여 관리한다.

| 섹터 | 대표 종목 | 섹터 레버리지 |
|------|----------|--------------|
| 반도체 | NVDA, AVGO, AMD, MU, TSM | SOXL / SOXS |
| 빅테크 | MSFT, AAPL, GOOGL, AMZN, META | QLD / QID |
| AI/소프트웨어 | PLTR, DDOG, CRM, ADBE, ORCL | ROM / REW |
| 전기차/에너지 | TSLA | TSLL / TSLS |
| 크립토 | MSTR, COIN, CLSK | BITX / SBIT |
| 금융 | BLK, BAC, JPM, V, MA | UYG / SKF |
| 양자컴퓨팅 | IONQ, RGTI | - |
| 엔터테인먼트 | DIS, DKNG | - |
| 헬스케어 | NVO, UNH, LLY | RXL / RXD |
| 소비재 | KO | - |
| 인프라/리츠 | NSC, EQIX | - |
| 기타 | UBER, SHOP | - |

### 유니버스 관리

대시보드 또는 API를 통해 종목을 추가/제거/활성화할 수 있다.

```bash
# 유니버스 조회
curl http://localhost:9500/universe

# 종목 추가
curl -X POST http://localhost:9500/universe/add \
  -H "Content-Type: application/json" \
  -d '{"ticker": "PLTR", "name": "Palantir", "direction": "bull", "leverage": 1.0}'

# 종목 활성/비활성 토글
curl -X POST http://localhost:9500/universe/toggle \
  -H "Content-Type: application/json" \
  -d '{"ticker": "PLTR", "enabled": true}'
```

---

## 2. 매매 전략 개요

### AI 의사결정 프로세스

```
뉴스 분석 (30개 소스)
    +
기술적 지표 (RSI, MACD, BB)
    +
매크로 환경 (VIX, Fear&Greed, CPI, 금리)
    +
시장 레짐 판별 (strong_bull ~ crash)
    +
RAG 과거 패턴 검색
    │
    ▼
Claude Opus 종합 판단
    │
    ├── BUY: 매수 (confidence >= 0.7)
    ├── SELL: 매도 (보유 중인 경우)
    └── HOLD: 관망 (명확한 시그널 없음)
```

### 진입 조건

- AI 신뢰도(confidence)가 `min_confidence` (기본 0.7) 이상이어야 한다
- 안전장치 체인 (HardSafety → SafetyChecker → RiskGate → EmergencyProtocol → CapitalGuard) 전체 통과
- 포지션 비율이 `max_position_pct` (기본 15%) 미만이어야 한다
- 전체 투자 비율이 `max_total_position_pct` (기본 80%) 미만이어야 한다
- VIX가 `vix_shutdown_threshold` (기본 35) 미만이어야 한다

### 청산 조건

| 조건 | 기본값 | 설명 |
|------|--------|------|
| 이익 실현 | +3.0% | `take_profit_pct` |
| 트레일링 스탑 | -1.5% | 최고가 대비 `trailing_stop_pct` 하락 시 |
| 손절 | -2.0% | `stop_loss_pct` |
| EOD 청산 | 활성화 | 장 마감 시 포지션 정리 (선택) |
| 최대 보유일 | 5일 | `max_hold_days` 초과 시 강제 청산 |
| AI 매도 판단 | - | Claude Opus가 매도 결정 시 |
| 긴급 프로토콜 | - | 긴급 정지 발동 시 전량 매도 |

---

## 3. 전략 파라미터

`strategy_params.json` 파일에서 전략 파라미터를 관리한다.

### 현재 설정값

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
    "enabled": true,
    "description": "시스템 운영비($300/월)를 반드시 수익으로 충당해야 한다"
  }
}
```

### 파라미터 설명

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `take_profit_pct` | 3.0 | 이익 실현 목표 (%) |
| `trailing_stop_pct` | 1.5 | 최고가 대비 트레일링 스탑 (%) |
| `stop_loss_pct` | -2.0 | 손절 한도 (%) |
| `eod_close` | true | 장 마감 시 포지션 자동 정리 |
| `min_confidence` | 0.7 | AI 최소 신뢰도 (0.0~1.0) |
| `max_position_pct` | 15.0 | 종목당 최대 포지션 비율 (%) |
| `max_total_position_pct` | 80.0 | 전체 최대 투자 비율 (%) |
| `max_daily_trades` | 30 | 일일 최대 매매 횟수 |
| `max_daily_loss_pct` | -5.0 | 일일 최대 손실 한도 (%) |
| `max_hold_days` | 5 | 최대 보유일 (초과 시 강제 청산) |
| `vix_shutdown_threshold` | 35 | VIX 서킷브레이커 임계값 |

### 파라미터 변경 방법

```bash
# API로 조회
curl http://localhost:9500/strategy/params

# API로 수정
curl -X POST http://localhost:9500/strategy/params \
  -H "Content-Type: application/json" \
  -d '{"take_profit_pct": 4.0, "trailing_stop_pct": 2.0}'
```

대시보드의 "전략 설정" 화면에서도 변경할 수 있다. 주간 분석에서 Claude AI가 파라미터 조정을 제안하면, 대시보드에서 승인/거부할 수 있다.

---

## 4. 리스크 관리

### 6단계 리스크 게이트 파이프라인

모든 주문은 6개의 리스크 게이트를 순차적으로 통과해야 한다.

| 단계 | 게이트 | 설명 |
|------|--------|------|
| 1 | DailyLossLimiter | 일일 누적 손실이 한도(-5%)를 초과하면 매수 차단 |
| 2 | ConcentrationLimiter | 단일 종목 포지션이 15%를 초과하면 추가 매수 차단 |
| 3 | LosingStreakDetector | N연패 감지 시 매매 쿨다운 (일정 시간 매매 중단) |
| 4 | SimpleVaR | 포트폴리오 VaR이 한도를 초과하면 신규 진입 차단 |
| 5 | RiskBudget | 월간 리스크 예산이 소진되면 포지션 사이즈 축소 |
| 6 | TrailingStopLoss | 트레일링 스탑 조건 충족 시 청산 트리거 |

### 리스크 설정 변경

```bash
# 리스크 상태 조회
curl http://localhost:9500/api/risk/status

# 게이트 상태 조회
curl http://localhost:9500/api/risk/gates

# 설정 변경
curl -X PUT http://localhost:9500/api/risk/config \
  -H "Content-Type: application/json" \
  -d '{"daily_loss_limit_pct": -3.0, "max_concentration_pct": 10.0}'

# 백테스트 실행 (현재 설정으로)
curl -X POST http://localhost:9500/api/risk/backtest/run
```

### 벤치마크 비교

시스템 수익률을 패시브 투자 벤치마크와 비교하여 성과를 평가한다.

- **SPY 매수후보유**: S&P 500 ETF 단순 보유 수익률
- **SSO 매수후보유**: S&P 500 2X 레버리지 ETF 단순 보유 수익률
- **AI 전략**: 시스템의 실제 매매 수익률

4주 연속 벤치마크 대비 언더퍼포먼스 발생 시 경고 알림을 발송한다.

---

## 5. 시장 시간 및 세션

### 미국 주식 시장 시간 (KST)

| 세션 | 비서머타임 (11월~3월) | 서머타임 (3월~11월) |
|------|---------------------|-------------------|
| Pre-market | 22:00~00:00 KST | 21:00~23:00 KST |
| 정규장 | 00:00~06:30 KST | 23:30~06:00 KST |
| After-market | 06:30~10:00 KST | 06:00~09:00 KST |

### 시스템 운영 시간 (KST)

| 시간 | 단계 | 동작 |
|------|------|------|
| 23:00 | LaunchAgent 시작 | 시스템 기동, Pre-market 준비 |
| 23:00~23:30 | 준비 단계 | 전체 크롤링, 분류, 분석 |
| 23:00~06:30 | 연속 분석 | 30분 주기 크롤링 + 시장 분석 |
| 정규장 시작 | 매매 루프 | 15분 주기 (크롤 → 분석 → 판단 → 실행) |
| 정규장 종료 | EOD 정리 | Overnight 판단, Daily Feedback |
| 06:30 | LaunchAgent 종료 | 시스템 안전 종료 |

### 세션별 동작

- **정규장**: 15분 주기 매매 루프 (전체 사이클 실행)
- **Pre/After-market**: 포지션 모니터링만 수행 (신규 진입 없음)
- **장 외**: Pre-market 준비 또는 EOD 정리

---

## 6. LaunchAgent 자동화

### 설치 및 관리

```bash
# 설치 (매일 23:00 KST 자동 시작)
cd scripts
./install_launchagent.sh install

# 상태 확인
./install_launchagent.sh status

# 수동 시작/종료
./install_launchagent.sh start
./install_launchagent.sh stop

# 제거
./install_launchagent.sh uninstall
```

### 자동화 동작 흐름

1. **23:00 KST**: macOS LaunchAgent가 `auto_trading.sh`를 실행한다
2. **네트워크 확인**: 인터넷 연결을 확인한다 (최대 5분 대기)
3. **Docker 시작**: Docker Desktop과 PostgreSQL/Redis 컨테이너를 시작한다
4. **시스템 기동**: Python 가상환경을 활성화하고 `src/main.py`를 실행한다
5. **프로세스 감시**: 1분 주기로 프로세스 상태를 확인한다
6. **자동 재시작**: 비정상 종료 시 자동 재시작한다 (최대 10회)
7. **06:30 KST**: 종료 시간 도달 시 SIGTERM으로 안전 종료한다

### 로그 확인

```bash
# 실시간 로그 모니터링
tail -f ~/Library/Logs/trading/auto_trading.log

# 시스템 표준 출력
tail -f ~/Library/Logs/trading/trading_stdout.log

# 오류 로그
tail -f ~/Library/Logs/trading/trading_stderr.log
```

### 슬립 방지

`auto_trading.sh`는 `caffeinate` 명령어를 사용하여 macOS가 절전 모드로 들어가는 것을 방지한다. 스크립트가 종료되면 자동으로 해제된다.

---

## 7. Telegram 봇 운용

### 자동 알림

시스템이 자동으로 발송하는 Telegram 알림:

| 알림 유형 | 발송 시점 | 내용 |
|----------|----------|------|
| 시스템 시작 | 시스템 기동 시 | 매매 모드, 계좌, Claude 모드 |
| 시스템 종료 | 시스템 종료 시 | 종료 유형, 일일 PnL |
| 매수 실행 | 매수 주문 체결 시 | 종목, 수량, 가격, AI 신뢰도, 사유 |
| 매도 실행 | 매도 주문 체결 시 | 종목, 수량, 수익률 |
| 긴급 경고 | 긴급 상황 발생 시 | VIX 급등, 일일 손실 한도 도달 |
| Pre-market 요약 | 준비 단계 완료 시 | HIGH 영향 뉴스, 시장 레짐 |
| 일일 보고서 | EOD 단계 완료 시 | 수익 요약, 포지션, 시장 분석 |
| 주간 보고서 | 일요일 | 주간 성과, 파라미터 조정 제안 |

### 봇 명령어 (양방향)

Telegram 봇에게 명령어를 보내 시스템을 원격 제어할 수 있다.

| 명령어 | 설명 |
|--------|------|
| `/status` | 현재 시스템 상태 조회 |
| `/positions` | 보유 포지션 목록 |
| `/balance` | 계좌 잔고 조회 |
| `/report` | 최신 일일 보고서 |
| `/buy TICKER` | 수동 매수 명령 |
| `/sell TICKER` | 수동 매도 명령 |
| `/emergency_stop` | 긴급 정지 (전량 매도) |
| `/emergency_resume` | 긴급 정지 해제 |

### 듀얼 수신

`.env`에 두 번째 Telegram 계정을 설정하면 동일한 알림을 두 곳에서 수신할 수 있다.

```bash
TELEGRAM_BOT_TOKEN_2=<두 번째 봇 토큰>
TELEGRAM_CHAT_ID_2=<두 번째 채팅 ID>
```

---

## 8. 대시보드 활용

### 메인 화면

Flutter 대시보드는 다음 정보를 실시간으로 표시한다:

- **계좌 요약**: 잔고, 평가 손익, 일일 수익률
- **포지션 목록**: 보유 종목, 수량, 평균가, 현재가, 수익률
- **최근 매매**: 최근 체결 내역
- **시스템 상태**: 가동 시간, 모듈 상태

### 차트 화면

| 차트 | 설명 |
|------|------|
| 일별 수익률 | 막대 차트 (양수: 녹색, 음수: 빨간색) |
| 누적 수익률 | 라인 차트 (AI vs SPY vs SSO 비교) |
| 종목별 히트맵 | 종목별 수익/손실 히트맵 |
| 시간대별 히트맵 | 시간대별 수익률 분포 |
| 드로다운 | 최대 낙폭 추적 차트 |
| Fear & Greed | CNN Fear & Greed 지수 게이지 |
| VIX 추이 | VIX 지수 라인 차트 |
| CPI 추이 | 소비자 물가지수 차트 |
| 금리 추이 | Fed Funds Rate 차트 |

### 분석 화면

| 화면 | 설명 |
|------|------|
| 종합 분석 | 종목별 AI 분석 결과 (차트 + 뉴스 + 예측) |
| RSI 화면 | Triple RSI (7/14/21) + Signal Line |
| 뉴스 | 날짜별 뉴스 목록 (한국어 번역 포함) |
| 매매 추론 | AI 매매 결정의 상세 근거 |
| 매매 원칙 | 7개 시스템 원칙 + 사용자 커스텀 원칙 |

### 관리 화면

| 화면 | 설명 |
|------|------|
| 전략 설정 | 전략 파라미터 조회/수정 |
| 유니버스 관리 | 종목 추가/제거/활성화 |
| 리스크 센터 | 리스크 게이트 상태, 백테스트 |
| 긴급 제어 | 긴급 정지/해제 |
| 수동 크롤링 | 크롤링 수동 실행 + 진행 상황 |
| 지표 가중치 | 기술적 지표 가중치 조정 |

---

## 9. 수익 목표 관리

### Survival Trading 원칙

시스템 운영비(Claude Pro/Max 구독, 서버 비용 등)를 반드시 매매 수익으로 충당해야 한다.

- **월간 비용**: $300 (기본 설정)
- **월간 목표**: $500 (비용 + 여유분)
- **공격성 자동 조정**: 목표 달성률에 따라 매매 공격성이 자동 조절된다

### 공격성 수준

| 수준 | 조건 | 동작 |
|------|------|------|
| `conservative` | 월 목표 80% 이상 달성 | 포지션 사이즈 축소, 높은 신뢰도 요구 |
| `normal` | 월 목표 40~80% 달성 | 표준 매매 |
| `aggressive` | 월 목표 40% 미만 달성 | 포지션 사이즈 확대, 적극적 진입 |

### 수익 목표 관리 API

```bash
# 현재 목표 조회
curl http://localhost:9500/api/target/current

# 월별 목표 설정
curl -X PUT http://localhost:9500/api/target/monthly \
  -H "Content-Type: application/json" \
  -d '{"target_usd": 600}'

# 공격성 수동 오버라이드
curl -X PUT http://localhost:9500/api/target/aggression \
  -H "Content-Type: application/json" \
  -d '{"aggression": "conservative"}'

# 수익 예측
curl http://localhost:9500/api/target/projection
```

---

## 10. 모의투자에서 실전 전환

### 전환 기준 (7가지)

시스템이 자동으로 평가하며, 모든 기준을 충족하면 Telegram으로 알림을 발송한다.

| 기준 | 조건 | 설명 |
|------|------|------|
| 1 | 최소 5거래일 | 충분한 테스트 기간 |
| 2 | 시스템 가동률 > 95% | 안정적 운영 |
| 3 | 누적 수익률 >= 0% | 최소한 손실 없음 |
| 4 | 최대 낙폭 < 10% | 리스크 관리 검증 |
| 5 | 성공 거래 3건 이상 | 실제 수익 달성 |
| 6 | 안전 시스템 통과 | 안전장치 정상 작동 |
| 7 | 비상 이벤트 0건 | 긴급 상황 미발생 |

### 전환 절차

1. 모의투자 모드에서 충분히 테스트한다 (최소 1~2주 권장)
2. 시스템이 "실전전환 준비 완료" 알림을 발송할 때까지 대기한다
3. `.env` 파일에서 매매 모드를 변경한다:

```bash
# 변경 전
KIS_MODE=virtual
TRADING_MODE=paper

# 변경 후
KIS_MODE=real
TRADING_MODE=live
```

4. 시스템을 재시작한다
5. 처음에는 작은 금액으로 시작하고, `max_position_pct`와 `max_total_position_pct`를 낮게 설정한다

### 주의사항

- 실전 전환 후에도 첫 1~2주는 보수적으로 운영한다
- `vix_shutdown_threshold`를 30으로 낮추는 것을 권장한다 (기본 35)
- 실전에서는 KIS 토큰이 실전 서버에서 발급된다
- 시장가 주문이 가능하지만, 슬리피지에 주의한다

---

## 11. 긴급 상황 대응

### 긴급 정지 (Emergency Stop)

전량 매도 후 신규 매수를 차단한다.

```bash
# API로 긴급 정지
curl -X POST http://localhost:9500/emergency/stop

# 텔레그램으로 긴급 정지
/emergency_stop

# 긴급 정지 해제
curl -X POST http://localhost:9500/emergency/resume
```

### 자동 트리거 조건

| 조건 | 동작 |
|------|------|
| VIX > 35 | 서킷브레이커: 신규 매수 차단 |
| 일일 손실 > -5% | 일일 매매 중단 |
| SPY 서킷브레이커 (하루 -3% 이상) | 신규 매수 차단 |
| 연속 5연패 | 매매 쿨다운 (일정 시간 매매 중단) |

### 수동 개입

시스템이 비정상 동작하는 경우:

```bash
# 1. 프로세스 확인
cat ~/Library/Logs/trading/trading.pid

# 2. 프로세스 종료
kill -SIGTERM $(cat ~/Library/Logs/trading/trading.pid)

# 3. 포트 정리
lsof -ti :9500 | xargs kill -9

# 4. Docker 확인
docker compose ps

# 5. 수동 재시작
source .venv/bin/activate
python -m src.main
```

---

## 12. 운용 체크리스트

### 일일 체크 (장 시작 전)

- [ ] Docker 컨테이너 실행 중인지 확인 (`docker compose ps`)
- [ ] LaunchAgent 상태 확인 (`./install_launchagent.sh status`)
- [ ] 텔레그램 "시스템 시작" 알림 수신 확인
- [ ] Pre-market 요약 알림 확인 (HIGH 영향 뉴스)
- [ ] VIX 수준 확인 (서킷브레이커 근접 여부)

### 장 중 체크

- [ ] 대시보드에서 포지션 및 PnL 모니터링
- [ ] 텔레그램 매매 알림 확인
- [ ] 비정상적인 매매 패턴 없는지 확인

### 장 후 체크

- [ ] 텔레그램 일일 보고서 확인
- [ ] 벤치마크 대비 성과 확인
- [ ] 보유 포지션의 Overnight 결정 확인
- [ ] 리스크 예산 잔여량 확인

### 주간 체크 (일요일)

- [ ] 주간 분석 리포트 확인
- [ ] 파라미터 조정 제안 검토 (승인/거부)
- [ ] 벤치마크 언더퍼포먼스 경고 확인
- [ ] 유니버스 종목 검토 (비활성 종목, 추가 필요 종목)
- [ ] Docker 볼륨 디스크 사용량 확인

### 월간 체크

- [ ] 수익 목표 달성률 확인
- [ ] 세금 현황 확인 (`/tax/status`)
- [ ] 슬리피지 통계 확인 (`/slippage/stats`)
- [ ] AI 사용량 통계 확인 (`/system/usage`)
- [ ] 환율 변동이 실효 수익률에 미치는 영향 확인

---

## 부록: 매매 원칙

시스템에 내장된 7개 핵심 매매 원칙이다. 대시보드의 "매매 원칙" 화면에서 확인하고, 사용자 커스텀 원칙을 추가할 수 있다.

매매 원칙은 `data/trading_principles.json` 파일에 저장되며, API를 통해 CRUD 할 수 있다.

```bash
# 원칙 목록 조회
curl http://localhost:9500/api/principles

# 새 원칙 추가
curl -X POST http://localhost:9500/api/principles \
  -H "Content-Type: application/json" \
  -d '{"title": "나만의 원칙", "content": "FOMO에 의한 매수를 절대 하지 않는다.", "category": "user"}'
```

원칙은 Claude AI의 매매 판단 시 시스템 프롬프트에 주입되어 AI의 의사결정에 영향을 미친다.

# AI Auto-Trading System V2 - Flutter 대시보드 가이드

## 개요

Flutter Desktop(macOS) 기반 모니터링 대시보드이다.
FastAPI 백엔드(localhost:9500)에 연결하여 포트폴리오, 차트, 뉴스, 리스크, 매매 근거를 실시간으로 모니터링한다.

## 기술 스택

- **프레임워크**: Flutter Desktop (macOS)
- **상태 관리**: Provider 패턴 (19개 Provider)
- **HTTP 클라이언트**: ApiService (localhost:9500)
- **실시간 통신**: WebSocket (3 채널)
- **차트**: fl_chart
- **테마**: GlassCard 기반 다크 테마

## 실행 방법

```bash
cd dashboard
flutter pub get
flutter run -d macos
```

API 서버가 실행 중이어야 한다 (`python3 -m src.main` 또는 독립 실행).

## 화면 구성 (20+ 화면)

### 1. Home Dashboard (홈 대시보드)

시스템 전체 상태를 한눈에 보여준다.

- 총자산, 현금, 오늘 PnL, 누적 수익
- 활성 포지션 수
- 시스템 상태 (NORMAL / WARNING / DANGER)
- 최근 알림 요약

### 2. Overview Screen (포트폴리오 개요)

포트폴리오 상세 정보를 표시한다.

- 보유 포지션 목록 (PositionCard)
- 종목별 비중 차트
- 미실현 손익
- 포트폴리오 구성

### 3. Trading Screen (실시간 매매)

실시간 매매 현황을 모니터링한다.

- WebSocket 기반 실시간 포지션 업데이트 (2초 주기)
- 실시간 매매 알림 (Redis Pub/Sub)
- 긴급 정지 버튼 (EmergencyButton)

### 4. Chart Dashboard (차트)

다양한 차트로 성과를 시각화한다.

- **PnL 라인 차트**: 일별 수익 추이 (PnlLineChart)
- **누적 수익 차트**: 누적 PnL 곡선 (CumulativeChart)
- **드로다운 차트**: 최대 낙폭 추적 (DrawdownChart)
- **티커 히트맵**: 종목 x 날짜 PnL (TickerHeatmap)
- **시간대 히트맵**: 시간 x 요일 성과 (HourlyHeatmap)

### 5. Analytics Screen (분석)

심층 분석 데이터를 표시한다.

- AI vs 벤치마크(SPY, SSO) 비교 차트
- 슬리피지 통계
- 최적 체결 시간대
- 승률, 평균 수익률, Sharpe Ratio

### 6. RSI Screen (Triple RSI)

Triple RSI(7/14/21) + Signal(9) 차트를 표시한다.

**최근 개선사항:**
- **종목 그룹 분류**: Big Tech (NVDA, AAPL, AMZN, META, GOOGL, MSFT, AMD), Index ETF (SPY, QQQ, IWM, DIA), Sector ETF (SOXX, XLK, XLF, XLE), Others (TSLA, COIN)
- **RSI 해석 텍스트**: 현재 RSI 수준에 따른 해석을 자동 표시
  - RSI < 20: "극단적 과매도 - 강한 반등 가능성"
  - RSI 20~30: "과매도 구간 - 매수 기회 탐색"
  - RSI 30~40: "약세 구간 - 추세 전환 주시"
  - RSI 40~60: "중립 구간 - 방향성 관망"
  - RSI 60~70: "강세 구간 - 추세 지속 여부 확인"
  - RSI 70~80: "과매수 구간 - 익절 고려"
  - RSI > 80: "극단적 과매수 - 조정 가능성 높음"
- **본주-레버리지 매핑 표시**: SOXL 선택 시 SOXX(본주) 데이터 사용 안내

### 7. News Screen (뉴스)

크롤링된 뉴스 기사를 날짜별로 표시한다.

**최근 개선사항:**
- **카테고리 필터링**: macro / earnings / company / sector / policy / geopolitics 카테고리별 필터
- **Major News 토글**: 고영향(high impact) 뉴스만 필터링하는 토글 버튼
- **한국어 요약**: AI가 생성한 한국어 뉴스 요약 표시
- 기사별 sentiment score, 방향(bullish/bearish/neutral), 관련 티커 표시

### 8. Trade Reasoning Screen (매매 근거)

AI의 매매 결정 근거를 날짜별로 표시한다.

- 거래별 AI 분석 근거 (signals, confidence, indicator direction)
- 사용자 피드백 추가 기능 (좋았다/나빴다)
- 일별 거래 통계 요약

### 9. Principles Screen (매매 원칙)

매매 원칙을 관리한다.

- 시스템 원칙 (7개, 수정 불가)
- 사용자 원칙 (추가/수정/삭제 가능)
- 카테고리별 그룹핑 (risk, strategy, execution)
- 우선순위 정렬

### 10. Universe Screen (ETF 유니버스)

매매 대상 ETF를 관리한다.

- 전체 유니버스 목록
- 티커 추가/삭제 (TickerAddDialog)
- 활성화/비활성화 토글
- 본주-레버리지 매핑 표시

### 11. Universe Manager Screen (매핑 관리)

본주-레버리지 ETF 매핑을 관리한다.

- 17종 매핑 목록
- 매핑 추가/삭제
- Bull(2X Long) / Bear(2X Inverse) 쌍 관리

### 12. Risk Center Screen (리스크 센터)

리스크 관리 상태를 표시한다.

- 안전 등급 (A/B/C/D)
- 6개 리스크 게이트 상태
- 일일 손실 한도 대비 현재 손실
- VIX 수준 표시

### 13. Risk Dashboard Screen (리스크 대시보드)

리스크 상세 데이터를 표시한다.

- 리스크 이벤트 이력
- 리스크 설정 파라미터
- 백테스트 결과

### 14. Profit Target Screen (수익 목표)

월간 수익 목표 달성 현황을 표시한다.

- 월간 목표 ($300 최소, $500 권장)
- 실현/미실현 PnL
- 달성률 게이지
- 공격성 수준 (보수적/정상/공격적)

### 15. Reports Screen (일일 리포트)

AI가 생성한 일일/주간 성과 리포트를 표시한다.

- 날짜별 리포트 목록
- 거래 요약, 종목별 분석
- 시간대별 성과 분석
- 지표별 진입 성과

### 16. Alert History (알림 이력)

시스템 알림 이력을 표시한다.

- 알림 유형별 필터 (trade, risk, emergency, system)
- 심각도별 필터 (info, warning, error, critical)
- 읽음/미읽음 상태 관리

### 17. Strategy Settings (전략 설정)

매매 전략 파라미터를 관리한다.

- take_profit_pct, stop_loss_pct, trailing_stop_pct
- min_confidence, max_position_pct
- max_daily_trades, max_daily_loss_pct
- vix_shutdown_threshold

### 18. Indicator Settings (지표 설정)

기술적 지표 가중치와 활성화 상태를 관리한다.

- 지표별 가중치 슬라이더 (합계 100)
- 프리셋 적용 (balanced, rsi_focused, macro_heavy)
- 개별 지표 활성화/비활성화

### 19. Settings Screen (시스템 설정)

시스템 전반 설정을 관리한다.

- 서버 연결 상태 확인
- API 포트 설정
- 로그 레벨 설정

### 20. Manual Crawl Screen (수동 크롤링)

수동 크롤링을 실행하고 진행 상태를 모니터링한다.

- 크롤링 시작 버튼
- WebSocket 기반 실시간 진행 상태 표시
- 소스별 수집 기사 수 표시

### 21. Macro Indicators

거시경제 지표를 표시한다.

**최근 개선사항:**
- **해석 텍스트 추가**: 모든 4개 주요 지표에 대해 현재 값에 따른 해석을 자동 표시
  - **VIX**: < 15 "매우 낮은 변동성", 15~20 "정상 범위", 20~30 "높은 변동성", 30+ "극단적 공포"
  - **Fed Rate**: 금리 수준에 따른 통화정책 해석
  - **CPI**: 인플레이션 수준 해석
  - **10Y-2Y Spread**: 수익률 곡선 역전/정상 해석

### 22. Fear & Greed Gauge

**최근 개선사항:**
- **점수 해석 텍스트**: 0~100 점수에 따른 해석을 자동 표시
  - 0~24: "극단적 공포 - 시장 패닉 상태"
  - 25~44: "공포 - 매수 기회 탐색"
  - 45~55: "중립 - 방향성 관망"
  - 56~74: "탐욕 - 주의 필요"
  - 75~100: "극단적 탐욕 - 조정 가능성"

### 23. Agent Team Screen (에이전트)

AI 에이전트 팀 구조를 시각화한다.

- 에이전트 팀 트리 (AgentTeamTree)
- 에이전트 상세 (AgentDetailScreen)

## 네비게이션

사이드바(SidebarNav) 기반 네비게이션을 사용한다.

```
SidebarNav
├── Home (HomeDashboard)
├── Overview (OverviewScreen)
├── Trading (TradingScreen)
├── Charts (ChartDashboard)
├── Analytics (AnalyticsScreen)
├── RSI (RsiScreen)
├── News (NewsScreen)
├── Trade Reasoning (TradeReasoningScreen)
├── Principles (PrinciplesScreen)
├── Universe (UniverseScreen)
├── Risk (RiskCenterScreen)
├── Profit Target (ProfitTargetScreen)
├── Reports (ReportsScreen)
├── Alerts (AlertHistory)
├── Settings (SettingsScreen)
└── Agents (AgentTeamScreen)
```

## API 연결

### ApiService

```dart
class ApiService {
  static const String baseUrl = 'http://localhost:9500';
  // GET, POST, PUT, DELETE 메서드
  // JSON 직렬화/역직렬화
  // 에러 핸들링
}
```

### WebSocketService

```dart
class WebSocketService {
  // /ws/positions - 2초 주기 포지션 업데이트
  // /ws/trades - 실시간 매매 알림
  // /ws/crawl/{taskId} - 크롤링 진행 상태
}
```

## 테마 시스템

### AppColors

Glass morphism 기반 다크 테마를 사용한다.

### AppTypography

일관된 타이포그래피 시스템을 적용한다.

### AppSpacing

8px 기반 간격 시스템을 사용한다.

### GlassCard

유리 효과 카드 위젯으로 모든 콘텐츠를 감싼다.

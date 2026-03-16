# DecisionMaker

## 역할
뉴스 신호(50%), 시장 레짐+매크로(30%), 기술적 지표(20%)를 종합하여 Claude Opus에 최종 매매 판단을 요청한다. 응답을 파싱 및 검증하여 실행 가능한 매매 명령 목록을 반환한다.

## 소속팀
의사결정팀 (Decision Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 뉴스 가중치 | 50% | 분류된 뉴스 신호 기여 비중 |
| 레짐/매크로 가중치 | 30% | 시장 레짐 + 매크로 데이터 기여 비중 |
| 기술적 지표 가중치 | 20% | RSI, MACD, 볼린저 밴드 등 기여 비중 |
| Claude 모델 | Opus | 매매 판단 (정확도 최우선) |
| 허용 action | buy/sell/hold/close | 반환 가능한 매매 행동 |
| 허용 direction | long/short | 방향 |
| 허용 time_horizon | intraday/swing | 보유 기간 |

## 동작 흐름
1. 분류된 뉴스 신호에서 관련 종목 추출
2. RAGRetriever로 과거 유사 사례 검색 (종목 + 레짐 기반)
3. IndicatorAggregator로 기술적 지표 종합 신호 생성
4. `build_trading_decision_prompt()` 로 Claude Opus 프롬프트 생성
5. Claude Opus 호출 (`trading_decision` 태스크 타입)
6. JSON 응답 파싱 및 필수 필드 검증 (action, ticker, confidence)
7. 유효하지 않은 action/direction 값 필터링
8. 최종 매매 명령 목록 반환

## 입력
- `classified_signals`: 분류된 뉴스 신호 목록
- `positions`: 현재 보유 포지션 목록
- `regime`: 현재 시장 레짐
- `price_data`: 종목별 가격 DataFrame
- `crawl_context`: 크롤링 AI 컨텍스트 (선택)
- `profit_context`: 수익 목표 컨텍스트 (선택)
- `risk_context`: 리스크 게이트 컨텍스트 (선택)

## 출력
- 매매 명령 목록, 각 항목:
  - `ticker`: 종목 심볼
  - `action`: buy/sell/hold/close
  - `confidence`: 0.0~1.0
  - `reason`: 판단 근거
  - `direction`: long/short (선택)
  - `time_horizon`: intraday/swing (선택)

## 의존성
- `ClaudeClient`: Claude Opus API 호출
- `RAGRetriever`: 과거 유사 사례 검색
- `IndicatorAggregator`: 기술적 지표 종합

## 소스 파일
`src/analysis/decision/decision_maker.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

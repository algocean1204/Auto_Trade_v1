# Short Term Trader

## 역할
5개 AI 페르소나 중 단기 매매 전문가이다. 당일~2일 이내 매매에 특화되며, 기술적 지표(RSI, VWAP, 볼린저, ATR)와 거래량 분석을 활용한다. 진입/청산 타이밍, 포지션 크기, 손절/익절 가격을 구체적으로 제시한다.

## 소속팀
의사결정팀 (Decision Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 모델 | Claude Sonnet | ComprehensiveTeam._run_agent()에서 호출 |
| 확신도 가중치 | 20% | RISK_MANAGER와 동일 |
| 실행 순서 | 4번째 | 이전 3개 에이전트 결과 참조 |
| 매매 기간 | 당일~2일 | 단기 매매 특화 |
| 전략 원칙 | 생존 매매 | 월 $300 최소 수익, 작은 이익 다수 |

## 동작 흐름
1. 이전 3개 에이전트(News, Macro, Risk)의 분석 결과 수신
2. RSI, VWAP, 볼린저 밴드, ATR 등 기술적 지표 분석
3. 거래량 분석으로 매매 신호 확인
4. 구체적 진입/청산 타이밍 제시
5. 포지션 크기(size_pct) 결정
6. 손절/익절 가격 설정
7. 강세장 → bull ETF, 약세장 → inverse ETF 권장

## 입력
- AnalysisContext (뉴스 요약, 기술 지표, 레짐, 포지션, 시장 데이터)
- 이전 3개 에이전트의 분석 결과 (prior_results)

## 출력
- JSON: action(BUY/SELL/HOLD), ticker, confidence, size_pct, reason

## 의존성
- `ComprehensiveTeam`: 순차 실행 오케스트레이터
- `PromptRegistry`: 시스템 프롬프트 제공
- `AiClient`: Claude Sonnet API 호출

## 소스 파일
- 실행: `src/analysis/team/comprehensive_team.py`
- 프롬프트: `src/analysis/prompts/prompt_registry.py`

## 상태
- 활성: ✅
- 유형: AI 페르소나 (Claude Sonnet)

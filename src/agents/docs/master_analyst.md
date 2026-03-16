# Master Analyst

## 역할
5개 AI 페르소나 중 최종 종합 분석가이다. 이전 4개 에이전트(News Analyst, Macro Strategist, Risk Manager, Short Term Trader)의 분석 결과를 종합하여 최종 매매 판단과 신호를 생성한다. 확신도 가중치 35%로 가장 높은 영향력을 갖는다.

## 소속팀
의사결정팀 (Decision Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 모델 | Claude Sonnet | ComprehensiveTeam._run_agent()에서 호출 |
| 확신도 가중치 | 35% | 5개 에이전트 중 최고 |
| 실행 순서 | 5번째 (마지막) | 4개 에이전트의 prior_results를 모두 참조 |
| 목표 | 월 $300 최소 수익 | 생존 매매 원칙 |
| 진입 기준 | 확신도 0.8+ | 불확실하면 현금 보유 권장 |

## 동작 흐름
1. 이전 4개 에이전트의 분석 결과(prior_results)를 JSON으로 수신
2. 뉴스 요약, 기술 지표, 레짐, 포지션, 시장 데이터를 종합 분석
3. 리스크 관리 최우선 원칙으로 매매 신호 생성
4. VIX 레짐에 따라 전략 조절 (crash 시 인버스 ETF 선호)
5. JSON 응답: signals/confidence/recommendations 키 포함

## 입력
- AnalysisContext (뉴스 요약, 기술 지표, 레짐, 포지션, 시장 데이터)
- 이전 4개 에이전트의 분석 결과 (prior_results)

## 출력
- JSON: signals(매매 신호 리스트), confidence(0.0~1.0), recommendations(권고사항)

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

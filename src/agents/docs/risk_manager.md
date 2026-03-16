# Risk Manager

## 역할
5개 AI 페르소나 중 리스크 관리 담당이다. 자본 보전을 최우선으로 하며, 포트폴리오 전체 손실을 -3% 이내로 제한한다. 포지션 집중도, 섹터 상관관계, 레버리지 디케이를 평가하고 위험 수준을 분류한다.

## 소속팀
의사결정팀 (Decision Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 모델 | Claude Sonnet | ComprehensiveTeam._run_agent()에서 호출 |
| 확신도 가중치 | 20% | NEWS_ANALYST(10%), MACRO(15%)보다 높음 |
| 실행 순서 | 3번째 | News Analyst, Macro Strategist 결과 참조 |
| 손실 한도 | -3% | 포트폴리오 전체 손실 제한 목표 |
| 위험 수준 | 4단계 | low/medium/high/critical |

## 동작 흐름
1. 이전 2개 에이전트(News Analyst, Macro Strategist)의 분석 결과 수신
2. 포지션 집중도, 섹터 상관관계 평가
3. 레버리지 디케이 리스크 분석
4. VIX 급등, 유동성 감소, 스프레드 확대 등 위험 신호 감지
5. 위험 수준(low/medium/high/critical) 분류
6. 구체적 대응 방안 제시 (포지션 축소, 헤지, 현금화 등)

## 입력
- AnalysisContext (뉴스 요약, 기술 지표, 레짐, 포지션, 시장 데이터)
- 이전 2개 에이전트의 분석 결과 (prior_results)

## 출력
- JSON: risk_level(위험 수준), warnings(경고 리스트), actions(대응 방안)

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

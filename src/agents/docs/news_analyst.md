# News Analyst

## 역할
5개 AI 페르소나 중 뉴스 분석 담당이다. 금융 뉴스의 시장 영향도를 0.0~1.0으로 평가하고 방향성을 판단한다. 매크로/실적/정책/섹터/지정학 5개 카테고리로 분류하며, 단기(1일 이내) 가격 영향에 초점을 맞춘다.

## 소속팀
분석팀 (Analysis Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 모델 | Claude Sonnet | ComprehensiveTeam._run_agent()에서 호출 |
| 확신도 가중치 | 10% | 5개 에이전트 중 최저 |
| 실행 순서 | 1번째 | prior_results 없이 독립 분석 |
| 카테고리 | 5개 | 매크로/실적/정책/섹터/지정학 |
| 초점 | 단기 | 1일 이내 가격 영향 |

## 동작 흐름
1. 뉴스 요약, 기술 지표, 레짐, 시장 데이터를 수신
2. 각 뉴스의 시장 영향도를 0.0~1.0으로 평가
3. 방향성(bullish/bearish/neutral) 판단
4. 5개 카테고리로 분류 (매크로, 실적, 정책, 섹터, 지정학)
5. 과거 유사 뉴스의 시장 반응 패턴 참고
6. JSON 응답: signals 리스트에 각 뉴스의 분석 결과 포함

## 입력
- AnalysisContext (뉴스 요약, 기술 지표, 레짐, 포지션, 시장 데이터)

## 출력
- JSON: signals(뉴스별 영향도/방향성/카테고리), confidence(0.0~1.0)

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

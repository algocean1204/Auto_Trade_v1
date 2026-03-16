# Macro Strategist

## 역할
5개 AI 페르소나 중 거시경제 분석 담당이다. FOMC, 고용, CPI, PMI 등 주요 경제 지표의 영향을 평가하고, 달러 인덱스, 국채 금리, 원자재 가격 등 교차 자산 신호를 분석한다. 레버리지 ETF에 유리/불리한 매크로 조건을 판별한다.

## 소속팀
의사결정팀 (Decision Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 모델 | Claude Sonnet | ComprehensiveTeam._run_agent()에서 호출 |
| 확신도 가중치 | 15% | NEWS_ANALYST(10%)보다 높음 |
| 실행 순서 | 2번째 | News Analyst 결과 참조 |
| 전망 기간 | 1~2주 | 향후 경기 전망 |
| 분석 대상 | 교차 자산 | 달러, 금리, 원자재, VIX |

## 동작 흐름
1. News Analyst의 분석 결과(prior_results)를 수신
2. FOMC, 고용, CPI, PMI 등 주요 경제 지표 영향 평가
3. 달러 인덱스, 국채 금리, 원자재 가격 교차 분석
4. 현재 경기 사이클 위치 판단
5. 향후 1~2주 매크로 전망 제시
6. 레버리지 ETF에 유리/불리한 조건 명시

## 입력
- AnalysisContext (뉴스 요약, 기술 지표, 레짐, 포지션, 시장 데이터)
- News Analyst의 분석 결과 (prior_results)

## 출력
- JSON: macro_view(매크로 전망), regime_assessment(레짐 평가), signals(매매 신호)

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

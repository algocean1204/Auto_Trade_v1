# WeeklyAnalysis

## 역할
매주 일요일에 자동 실행되어 한 주간의 매매 결과를 Claude Opus로 심층 분석하고, 시스템 파라미터 조정 제안을 pending_adjustments 테이블에 생성한다.

## 소속팀
모니터링팀 (Monitoring Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| Claude 모델 | Opus | 주간 심층 분석 (정확도 최우선) |
| 분석 대상 | trades 테이블 해당 주 기록 | 월~금 체결 이력 |
| 실행 주기 | 매주 일요일 1회 | main.py 주간 분석 루프에서 실행 |
| 파라미터 조정 | ParamAdjuster 연동 | 전략 파라미터 자동 조정 제안 |
| 저장 테이블 | feedback_reports (weekly) | 주간 리포트 영속화 |
| 조정 제안 테이블 | pending_adjustments | 사용자 승인 대기 파라미터 변경 |

## 동작 흐름
1. `generate(week_start)` 호출 (기본: 직전 월요일)
2. `trades` 테이블에서 해당 주 (월~금) 기록 로드
3. 주간 통계 계산 (일별 분해 포함):
   - 총손익, 일별 손익, 최대 드로다운
   - 일별 승률, 최고 성과일, 최저 성과일
   - 레짐별 성과 분해
4. `build_weekly_analysis_prompt()` 로 Claude Opus 프롬프트 생성
5. Claude Opus 호출 (`weekly_analysis` 태스크 타입)
6. 파라미터 조정 제안 파싱
7. `ParamAdjuster` 로 제안 검증 및 `pending_adjustments` 저장
8. `FeedbackReport` DB 저장 (weekly 타입)

## 입력
- `week_start`: 주 시작일 (월요일, YYYY-MM-DD, 기본: 직전 월요일)

## 출력
- 주간 분석 딕셔너리:
  - `week_start`: 주 시작일
  - `summary`: 주간 성과 요약
  - `daily_breakdown`: 일별 상세
  - `param_adjustments`: 파라미터 조정 제안 목록
  - `next_week_strategy`: 다음 주 전략 제안

## 의존성
- `ClaudeClient`: Claude Opus API 호출
- `ParamAdjuster`: 파라미터 조정 제안 검증 및 저장
- `PostgreSQL (Trade, FeedbackReport, PendingAdjustment 모델)`: 데이터 처리

## 소스 파일
`src/orchestration/phases/weekly_analysis.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

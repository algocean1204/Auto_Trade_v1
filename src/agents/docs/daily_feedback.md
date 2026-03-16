# DailyFeedback

## 역할
장 마감 후 당일 매매 기록을 Claude Opus가 자동 분석하여 일일 피드백 리포트를 생성한다. 생성된 피드백은 feedback_reports 테이블에 저장되고, 손실 교훈과 수익 패턴이 RAG 문서로 자동 변환된다.

## 소속팀
모니터링팀 (Monitoring Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| Claude 모델 | Opus | 일일 피드백 생성 (정확도 최우선) |
| 분석 대상 | trades 테이블 당일 기록 | 체결된 매매 이력 |
| 실행 주기 | 장 마감 후 1회 | EOD 단계에서 실행 |
| RAG 변환 | RAGDocUpdater 연동 | 손실 교훈 + 수익 패턴 자동 문서화 |
| 저장 테이블 | feedback_reports | 피드백 리포트 영속화 |

## 동작 흐름
1. `generate(target_date)` 호출 (기본: 오늘)
2. `trades` 테이블에서 해당일 체결 기록 로드
3. 기본 통계 계산:
   - 총손익 (USD), 수익률 (%), 승률 (%)
   - 평균 보유시간, 거래 수, 최대 손실, 최대 이익
4. `build_daily_feedback_prompt()` 로 Claude Opus 프롬프트 생성
5. Claude Opus 호출 (`daily_feedback` 태스크 타입)
6. 응답 파싱: 잘한 점, 개선할 점, 내일 전략
7. `FeedbackReport` DB 저장
8. `RAGDocUpdater.update_from_daily(feedback)` 로 RAG 문서 생성

## 입력
- `target_date`: 분석 대상 날짜 (YYYY-MM-DD, 기본: 오늘)

## 출력
- 피드백 딕셔너리:
  - `date`: 분석 날짜
  - `total_pnl_usd`: 총손익 (USD)
  - `total_pnl_pct`: 수익률 (%)
  - `trade_count`: 거래 수
  - `win_rate`: 승률 (%)
  - `analysis`: Claude Opus 분석 텍스트
  - `improvements`: 개선 제안 목록

## 의존성
- `ClaudeClient`: Claude Opus API 호출
- `RAGDocUpdater`: RAG 문서 자동 생성
- `PostgreSQL (Trade, FeedbackReport 모델)`: 데이터 로드 및 저장

## 소스 파일
`src/analysis/feedback/eod_feedback_report.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

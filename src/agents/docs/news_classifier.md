# NewsClassifier

## 역할
크롤링된 뉴스 기사를 Claude Sonnet으로 배치 분류한다. 영향도(high/medium/low), 방향성(bullish/bearish/neutral), 카테고리(earnings/macro/policy/sector 등)를 판별하며 델타 분류로 이전 결과 대비 변화분만 업데이트한다.

## 소속팀
분석팀 (Analysis Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| batch_size | 20 | 한 번에 분류할 기사 수 (토큰 효율 최적화) |
| Claude 모델 | Sonnet | 분류 작업용 (빠르고 효율적) |
| 유효 영향도 | high/medium/low | 분류 결과 허용 값 |
| 유효 방향 | bullish/bearish/neutral | 감성 방향 |
| 유효 카테고리 | earnings/macro/policy/sector/company/geopolitics/other | 7가지 카테고리 |
| 결과 저장 | data/classified_signals.json | 분류 결과 영속화 파일 |

## 동작 흐름
1. 미분류 기사 목록 로드 (DB 또는 파일)
2. 20개씩 배치로 분할
3. 각 배치에 대해 `build_news_classification_prompt()` 생성
4. Claude Sonnet 호출 (`news_classification` 태스크 타입)
5. JSON 응답 파싱 및 필수 필드 검증
6. 유효하지 않은 열거형 값 정제
7. 기존 신호와 비교하여 변화분만 업데이트 (델타 분류)
8. 분류 결과를 `classified_signals.json`에 저장

## 입력
- 크롤링된 기사 목록 (title, content, source, published_at 포함)

## 출력
- 기사별 분류 결과:
  - `id`: 기사 ID
  - `impact`: high/medium/low
  - `tickers`: 관련 종목 리스트
  - `direction`: bullish/bearish/neutral
  - `sentiment_score`: 0.0~1.0
  - `category`: 카테고리

## 의존성
- `ClaudeClient`: Claude Sonnet API 호출
- `RuleBasedFilter`: 1차 규칙 필터 (MLXClassifier 사용 시)
- `data/classified_signals.json`: 결과 영속화

## 소스 파일
`src/analysis/classifier/news_classifier.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

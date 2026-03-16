# CrawlVerifier

## 역할
크롤링 결과의 품질을 Claude Sonnet을 통해 검증한다. 최소 소스 성공률, 기사 수, 중복 비율 등 품질 임계값을 체크하는 검증 프롬프트를 생성하고 응답을 파싱한다.

## 소속팀
크롤링팀 (Crawling Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| MIN_SOURCES_RATIO | 0.5 (50%) | 최소 소스 성공률 (전체 소스 중 데이터 반환 소스 비율) |
| MIN_ARTICLES_COUNT | 10 | 최소 총 기사 수 |
| MAX_DUP_RATIO | 0.7 (70%) | 최대 허용 중복 비율 |
| Claude 모델 | Sonnet | 검증 프롬프트 처리 (빠르고 효율적) |

## 동작 흐름
1. `build_verification_prompt(crawl_result)` 호출
2. 소스별 성공/실패 통계, 중복률, 총 기사 수 집계
3. Claude Sonnet용 구조화 프롬프트 생성
4. 오케스트레이터(main.py)가 FallbackRouter를 통해 Claude 호출
5. `parse_verification_result(response)` 로 응답 파싱
6. `overall_quality` 결정 (good/acceptable/poor)
7. 실패 소스 목록 및 개선 제안 추출

## 입력
- `crawl_result`: CrawlEngine.run() 반환 딕셔너리
  - `source_stats`, `total_raw`, `duplicates_removed`, `kept`, `saved`, `mode`

## 출력
- `overall_quality`: "good" / "acceptable" / "poor"
- `sources_ratio`: 소스 성공률
- `failed_sources`: 실패한 소스 목록
- `recommendations`: 개선 제안 목록

## 의존성
- `ClaudeClient` (FallbackRouter를 통해 간접 사용): 실제 API 호출
- `CrawlEngine`: 검증 대상 결과 제공

## 소스 파일
`src/crawlers/verifier/crawl_verifier.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

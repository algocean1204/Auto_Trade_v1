# CrawlEngine

## 역할
30개 뉴스 소스(RSS, Reddit, SEC EDGAR, Stocktwits, API 등)를 병렬로 크롤링하여 기사를 수집하고 PostgreSQL에 저장한다. 중복 제거 및 규칙 기반 필터링을 적용하며 델타 크롤링을 통해 이미 수집된 기사는 재처리하지 않는다.

## 소속팀
크롤링팀 (Crawling Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| 소스 수 | 30개 | RSS, Reddit, SEC EDGAR, Stocktwits, Finviz, Fear&Greed, Polymarket, Kalshi 등 |
| 동시 실행 | 비동기 병렬 | asyncio 기반 전체 소스 병렬 처리 |
| 크롤링 모드 | full / delta | full: 전체 크롤링, delta: 마지막 체크포인트 이후 신규만 |
| 중복 제거 | DedupChecker | URL + 제목 해시 기반 중복 탐지 |
| Tier 스케줄 | Addendum 27 | 소스 중요도별 Tier 분류, 차등 폴링 주기 |

## 동작 흐름
1. `run(mode="full" | "delta")` 호출
2. `CRAWL_SOURCES` 설정에서 활성 소스 목록 로드
3. 소스 타입별 크롤러(RSSCrawler, RedditCrawler 등) 인스턴스화
4. `asyncio.gather`로 모든 크롤러 병렬 실행
5. `DedupChecker`로 중복 기사 제거
6. `RuleBasedFilter`로 관련성 없는 기사 필터링
7. 신규 기사를 `Article` 모델로 PostgreSQL 저장
8. `CrawlCheckpoint` 업데이트 (델타 크롤링용)
9. 결과 통계 반환 (`saved`, `total_raw`, `duplicates_removed` 등)

## 입력
- `mode`: "full" (전체) 또는 "delta" (증분)
- `source_keys`: 특정 소스만 실행 시 키 목록 (선택)

## 출력
- `saved`: 신규 저장된 기사 수
- `total_raw`: 크롤링된 원시 기사 총 수
- `duplicates_removed`: 중복 제거된 수
- `kept`: 필터 통과 수
- `discarded`: 필터 제거 수
- `source_stats`: 소스별 상세 통계

## 의존성
- `CrawlScheduler`: 소스별 크롤링 주기 관리
- `DedupChecker`: 중복 탐지
- `RuleBasedFilter`: 관련성 필터링
- `PostgreSQL (Article, CrawlCheckpoint 모델)`: 데이터 저장
- `Redis`: 체크포인트 캐싱

## 소스 파일
`src/crawlers/engine/crawl_engine.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

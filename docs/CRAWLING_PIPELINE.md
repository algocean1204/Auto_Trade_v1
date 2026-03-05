# AI Auto-Trading System V2 - 크롤링 파이프라인

## 개요

30개 이상의 글로벌 뉴스/데이터 소스에서 실시간으로 정보를 수집하고,
AI가 분류하여 매매 결정의 핵심 입력으로 활용한다.

## 소스 구성 (31개)

### US 소스 (11개)

| 소스 | 유형 | 우선순위 | 설명 |
|------|------|----------|------|
| Reuters | RSS | 1 (Critical) | 글로벌 뉴스 통신사 |
| Bloomberg | RSS | 1 (Critical) | 시장/경제 뉴스 |
| WSJ | RSS | 1 (Critical) | 월스트리트 저널 |
| SEC EDGAR | API | 1 (Critical) | 미국 증권거래위원회 공시 |
| Yahoo Finance | RSS | 2 (Important) | 종합 금융 뉴스 |
| CNBC | RSS | 2 (Important) | 미국 경제 전문 방송 |
| MarketWatch | RSS | 2 (Important) | 시장 분석 뉴스 |
| Finnhub | API | 2 (Important) | 실시간 시장 데이터 |
| AlphaVantage | API | 2 (Important) | 주가/경제 데이터 |
| Reddit WSB | Reddit API | 3 (Supplementary) | r/wallstreetbets |
| Reddit Investing | Reddit API | 3 (Supplementary) | r/investing |

### 유럽 소스 (4개)

| 소스 | 유형 | 우선순위 | 설명 |
|------|------|----------|------|
| Financial Times | RSS | 1 (Critical) | 글로벌 경제 전문지 |
| ECB Press | RSS | 1 (Critical) | 유럽중앙은행 발표 |
| BBC Business | RSS | 2 (Important) | BBC 경제 섹션 |
| Investing.com | Scraping | 2 (Important) | 글로벌 금융 포털 |

### 아시아 소스 (2개)

| 소스 | 유형 | 우선순위 | 설명 |
|------|------|----------|------|
| Nikkei Asia | RSS | 2 (Important) | 일본 경제 전문지 |
| SCMP | RSS | 2 (Important) | 사우스차이나모닝포스트 |

### 한국 소스 (5개)

| 소스 | 유형 | 우선순위 | 설명 |
|------|------|----------|------|
| Yonhap English | RSS | 2 (Important) | 연합뉴스 영문판 |
| Hankyung | RSS | 3 (Supplementary) | 한국경제신문 |
| MK (Maeil Business) | RSS | 3 (Supplementary) | 매일경제 |
| Naver Finance | Scraping | 3 (Supplementary) | 네이버 금융 |
| StockNow | Scraping | 4 (Supplementary-KR) | StockNow 한국 |

### 글로벌 매크로 소스 (5개)

| 소스 | 유형 | 우선순위 | 설명 |
|------|------|----------|------|
| Fed Announcements | RSS | 1 (Critical) | 미국 연방준비제도 |
| Finviz | Scraping | 1 (Critical) | 시장 스크리너 |
| FRED | API | 2 (Important) | 경제 데이터 |
| CNN Fear & Greed | Scraping | 2 (Important) | 공포/탐욕 지수 |
| StockTwits | API | 3 (Supplementary) | 소셜 트레이딩 |

### 기타 소스 (4개)

| 소스 | 유형 | 우선순위 | 설명 |
|------|------|----------|------|
| DART | API | 3 (Supplementary) | 한국 금감원 공시 |
| Polymarket | Scraping | 3 (Supplementary) | 예측 시장 |
| Kalshi | Scraping | 3 (Supplementary) | 예측 시장 |
| Economic Calendar | API | 2 (Important) | 경제 이벤트 캘린더 |

## CrawlScheduler

### Night/Day 모드

KST 기준으로 야간 모드(미국 장 시간)와 주간 모드를 자동 판별하여
소스별 크롤링 주기를 동적으로 조절한다.

#### Night Mode (23:00~06:30 KST)

미국 장 시간대이므로 공격적으로 크롤링한다.

| 소스 | 간격 | 설명 |
|------|------|------|
| Finnhub | 5분 | 실시간 시장 데이터 |
| Finviz | 5분 | 시장 스크리너 |
| Naver Finance | 10분 | 한국 시장 반응 |
| AlphaVantage | 30분 | 주가 데이터 |
| Investing.com | 30분 | 글로벌 지표 |
| Polymarket | 30분 | 예측 시장 |
| Kalshi | 30분 | 예측 시장 |
| CNN Fear & Greed | 1시간 | 공포/탐욕 지수 |
| FRED | 1시간 | 경제 데이터 |
| StockNow | 1시간 | 한국 주식 커뮤니티 |
| RSS Feeds | 15분 | 15개 RSS 소스 |

#### Day Mode (06:30~23:00 KST)

미국 장 외 시간대이므로 완화된 주기로 크롤링한다.

| 소스 | 간격 | 설명 |
|------|------|------|
| Finnhub | 15분 | 축소 |
| Finviz | 비활성 | 장 외 |
| AlphaVantage | 비활성 | 장 외 |
| RSS Feeds | 30분 | 축소 |
| Naver Finance | 30분 | 한국 장 시간 |

## 크롤링 파이프라인

### Full Crawling (Pre-market, 23:05~23:25)

```
[1] CrawlEngine.run_full()
     │
     ├── RSS Feeds (15개 소스, 병렬)
     │   ├── feedparser로 RSS 파싱
     │   └── 기사별 headline, content, url, published_at 추출
     │
     ├── API Sources (병렬)
     │   ├── Finnhub: /news endpoint
     │   ├── AlphaVantage: news sentiment
     │   ├── FRED: 경제 지표
     │   └── SEC EDGAR: 최신 공시
     │
     ├── Scraping (병렬)
     │   ├── Finviz: 뉴스 + 시장 스크리너 (BeautifulSoup)
     │   ├── Investing.com: 경제 캘린더 (Playwright)
     │   ├── CNN Fear & Greed: 지수 (httpx)
     │   ├── Naver Finance: 한국 뉴스 (BeautifulSoup)
     │   ├── StockNow: 한국 커뮤니티 (httpx)
     │   ├── Polymarket: 예측 시장 (httpx)
     │   └── Kalshi: 예측 시장 (httpx)
     │
     └── Social (병렬)
         ├── Reddit: PRAW API (r/wallstreetbets, r/investing)
         └── StockTwits: REST API
     │
     v
[2] Dedup (Redis 기반 중복 제거)
     ├── content_hash (SHA-256) 기반 정확 중복 제거
     └── Redis SET으로 24시간 TTL 관리
     │
     v
[3] Rule Filter (룰 기반 필터링)
     ├── 최소 content 길이 필터
     ├── 블랙리스트 소스 제외
     └── 언어 필터 (영어 우선)
     │
     v
[4] DB 저장 (articles 테이블)
     ├── headline, content, url, source, published_at
     ├── language, content_hash (unique)
     └── is_processed = false
```

### Delta Crawling (Regular Market, 15분 주기)

```
[1] CrawlEngine.run_delta()
     │
     ├── 변경 감지: CrawlCheckpoint 이후의 새 기사만
     ├── Tier 1 소스만 우선 수집 (Finviz, 고우선순위 RSS)
     └── 소스별 마지막 fetch 시간 비교
     │
     v
[2] Dedup → Filter → DB 저장 (위와 동일)
```

## 분류 파이프라인

### NewsClassifier (Claude Sonnet)

```
articles (is_processed = false)
     │
     v
[1] 배치 처리 (10개씩)
     │
     v
[2] Claude Sonnet 호출
     │
     ├── 입력: headline + content (최대 1000자)
     │
     ├── 분류 결과:
     │   ├── category: macro / earnings / company / sector / policy / geopolitics
     │   ├── impact: high / medium / low
     │   ├── direction: bullish / bearish / neutral
     │   ├── tickers_mentioned: ["NVDA", "SOXL", ...]
     │   └── sentiment_score: -1.0 ~ 1.0
     │
     └── DB 업데이트:
         ├── articles.classification = {...}
         ├── articles.tickers_mentioned = [...]
         ├── articles.sentiment_score = 0.75
         └── articles.is_processed = true
     │
     v
[3] 고영향 뉴스 알림
     ├── impact == "high" → Telegram 즉시 알림
     └── 관련 티커 보유 중 → 추가 알림
```

### MLX 로컬 분류 (대안)

Claude API 장애 또는 할당량 초과 시 로컬 MLX 모델로 폴백한다.

```
articles (미분류)
     │
     v
MLXClassifier (Qwen3-30B-A3B)
     ├── Apple Silicon MPS 가속
     ├── 분류 정확도: Claude 대비 약 85%
     └── 응답 시간: 2~5초 (로컬)
```

## 분류 카테고리 상세

| 카테고리 | 설명 | 예시 |
|----------|------|------|
| macro | 거시경제 | Fed 금리 결정, CPI 발표, 고용 보고서 |
| earnings | 실적 | 분기 실적 발표, 가이던스 변경 |
| company | 개별 기업 | CEO 교체, 제품 출시, 인수합병 |
| sector | 섹터 | 반도체 수출 규제, AI 투자 확대 |
| policy | 정책 | 관세, 무역 정책, 규제 변화 |
| geopolitics | 지정학 | 미중 관계, 대만 해협, 중동 갈등 |

## 영향도 기준

| 영향도 | 기준 | 알림 |
|--------|------|------|
| high | 시장 전체에 즉각적 영향 | Telegram 즉시 알림 |
| medium | 특정 섹터/종목에 영향 | 대시보드 표시 |
| low | 참고 수준 | 로그만 기록 |

## CrawlVerifier

Full Crawling 완료 후 크롤링 품질을 검증한다.

```
크롤링 결과
     │
     v
CrawlVerifier (Claude Sonnet)
     ├── 수집 기사 수 적정성 확인
     ├── 소스별 커버리지 확인
     ├── 중복률 체크
     ├── 시간 분포 확인 (오래된 기사 비율)
     └── 품질 등급: PASS / WARN / FAIL
```

## 데이터 저장

### articles 테이블

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| source | VARCHAR(50) | 소스 이름 |
| headline | TEXT | 제목 |
| content | TEXT | 본문 |
| url | TEXT | 원문 링크 |
| published_at | TIMESTAMP | 발행 시간 |
| language | VARCHAR(5) | 언어 (en/ko) |
| tickers_mentioned | JSONB | 관련 티커 목록 |
| sentiment_score | FLOAT | 감성 점수 (-1.0~1.0) |
| classification | JSONB | 분류 결과 |
| is_processed | BOOLEAN | 분류 완료 여부 |
| crawled_at | TIMESTAMP | 크롤링 시간 |
| content_hash | VARCHAR(64) | 중복 방지 해시 (unique) |

### crawl_data 테이블

Finviz, Polymarket, Kalshi 등 구조화된 데이터를 저장한다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| source | VARCHAR(30) | 소스 이름 |
| data_type | VARCHAR(30) | 데이터 유형 |
| content | JSONB | 구조화된 데이터 |
| relevance_score | NUMERIC | 관련성 점수 |
| fetched_at | TIMESTAMP | 수집 시간 |
| expires_at | TIMESTAMP | 만료 시간 |

### fear_greed_history 테이블

CNN Fear & Greed 지수 이력을 저장한다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| date | DATE | 날짜 (unique) |
| score | INTEGER | 0~100 점수 |
| rating | VARCHAR(20) | Extreme Fear ~ Extreme Greed |
| sub_indicators | JSONB | 7개 하위 지표 |

### prediction_markets 테이블

Polymarket, Kalshi 등 예측 시장 데이터를 저장한다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| source | VARCHAR(20) | polymarket / kalshi |
| market_title | TEXT | 시장 제목 |
| category | VARCHAR(30) | 카테고리 |
| yes_probability | NUMERIC | Yes 확률 |
| volume | BIGINT | 거래량 |

## AI Context Builder

크롤링 + 분류 결과를 AI 분석용 컨텍스트로 변환한다.

```
build_ai_context_compact()
     │
     ├── 최근 고영향 뉴스 요약 (최대 20개)
     ├── 카테고리별 뉴스 분포
     ├── 현재 Fear & Greed 지수
     ├── 예측 시장 주요 이벤트
     ├── FRED 경제 지표 (VIX, Fed Rate, CPI)
     └── Finviz 시장 스크리너 데이터
     │
     v
 JSON 형식 컨텍스트 → DecisionMaker (Claude Opus)
```

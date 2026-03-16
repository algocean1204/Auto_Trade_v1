# CrawlScheduler

## 역할
KST(한국 표준시) 기준으로 야간 모드(미국 장 시간, 23:00~06:30)와 주간 모드(06:30~23:00)를 자동 판별하여 소스별 크롤링 폴링 주기를 동적으로 조절한다.

## 소속팀
크롤링팀 (Crawling Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| Night mode 기본 간격 | 900초 (15분) | 미국 장 시간, 공격적 폴링 |
| Day mode 기본 간격 | 1800초 (30분) | 한국 주간 시간, 완화된 폴링 |
| Night mode RSS 간격 | 600초 (10분) | RSS 피드 야간 폴링 |
| Day mode RSS 간격 | 1800초 (30분) | RSS 피드 주간 폴링 |
| finnhub 야간 | 300초 (5분) | 고속 주가 데이터 |
| alphavantage 주간 | 0초 (비활성) | 주간에는 alphavantage 비활성화 |
| cnn_fear_greed 주간 | 86400초 (1일) | 공포탐욕지수 하루 1회 |

## 동작 흐름
1. 현재 KST 시각 조회
2. 23:00~06:30 범위면 Night mode, 그 외는 Day mode 결정
3. `get_interval(source_key)` 호출 시 소스별 맞춤 간격 반환
4. `is_night_mode()` / `is_day_mode()` 속성으로 현재 모드 노출
5. CrawlEngine이 이 간격을 참조하여 소스 실행 주기 결정

## 입력
- 현재 시스템 시각 (ZoneInfo "Asia/Seoul")
- 소스 키 (source_key)

## 출력
- 해당 소스의 현재 모드 기반 폴링 간격 (초)
- 현재 모드 (`night` / `day`)

## 의존성
- Python `zoneinfo.ZoneInfo("Asia/Seoul")`: KST 시각 변환

## 소스 파일
`src/crawlers/scheduler/crawl_scheduler.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

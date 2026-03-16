# Redis 키 전체 목록 — 뉴스 사이클 관련

## 빠른 점검 명령

```bash
# 모든 뉴스/센티넬/분석 관련 키 조회
redis-cli KEYS "news:*" | sort
redis-cli KEYS "sentinel:*" | sort
redis-cli KEYS "analysis:*" | sort
redis-cli KEYS "vix:*" | sort
redis-cli KEYS "continuous_analysis:*" | sort
```

---

## 뉴스 파이프라인 키

| Redis 키 | 작성 모듈 | TTL | 용도 | 확인 명령 |
|---|---|---|---|---|
| `news:latest_titles` | news_pipeline.py | 300초(5분) | 센티넬 헤드라인 스캔용 | `redis-cli GET "news:latest_titles" \| python3 -m json.tool \| head -10` |
| `news:classified_latest` | news_pipeline.py | 86400초(24시간) | 분류 결과 누적 (trading_loop 참조) | `redis-cli GET "news:classified_latest" \| python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'건')"` |
| `news:daily:{YYYY-MM-DD}` | news_pipeline.py | 86400초 | Flutter 일별 기사 리스트 | `redis-cli GET "news:daily:$(date -u +%Y-%m-%d)" \| python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'건')"` |
| `news:latest_summary` | news_pipeline.py | 86400초 | 뉴스 요약 통계 (분석 컨텍스트용) | `redis-cli GET "news:latest_summary" \| python3 -m json.tool` |
| `news:summary:{YYYY-MM-DD}` | news_pipeline.py | 86400초 | Flutter 날짜별 요약 | `redis-cli EXISTS "news:summary:$(date -u +%Y-%m-%d)"` |
| `news:dates` | news_pipeline.py | 86400초 | Flutter 날짜 사이드패널 | `redis-cli GET "news:dates" \| python3 -m json.tool` |
| `news:article:{id}` | news_pipeline.py | 86400초 | Flutter 개별 기사 조회 | `redis-cli KEYS "news:article:*" \| wc -l` |
| `news:key_latest` | news_pipeline.py | 86400초 | 핵심 뉴스 (impact>=0.7) | `redis-cli GET "news:key_latest" \| python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'건')"` |
| `news:themes_latest` | news_pipeline.py | 86400초 | 반복 테마 추적 | `redis-cli GET "news:themes_latest" \| python3 -m json.tool \| head -10` |
| `news:situation_reports_latest` | news_pipeline.py | 86400초 | 상황 추적 보고서 | `redis-cli GET "news:situation_reports_latest" \| python3 -m json.tool \| head -10` |

---

## 센티넬 키

| Redis 키 | 작성 모듈 | TTL | 용도 | 확인 명령 |
|---|---|---|---|---|
| `sentinel:watch` | sentinel_loop.py | 3600초(1시간) | watch 수준 신호 누적 | `redis-cli GET "sentinel:watch" \| python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'건')"` |
| `sentinel:priority` | sentinel_loop.py | 7200초(2시간) | next_cycle 판정 신호 누적 | `redis-cli GET "sentinel:priority" \| python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'건')"` |

---

## 분석 키

| Redis 키 | 작성 모듈 | TTL | 용도 | 확인 명령 |
|---|---|---|---|---|
| `analysis:comprehensive_report` | continuous_analysis.py | 7200초(2시간) | 정기 Layer 2 분석 보고서 | `redis-cli GET "analysis:comprehensive_report" \| python3 -c "import sys,json;d=json.load(sys.stdin);print('confidence:',d.get('confidence'),'risk:',d.get('risk_level'))"` |
| `analysis:emergency_report` | sentinel_loop.py | 300초(5분) | 센티넬 긴급 보고서 (별도 키) | `redis-cli GET "analysis:emergency_report" \| python3 -m json.tool` |
| `continuous_analysis:latest` | continuous_analysis.py | 7200초 | 분석 결과 캐시 (레거시) | `redis-cli GET "continuous_analysis:latest" \| python3 -m json.tool \| head -10` |

---

## 시장 데이터 키

| Redis 키 | 작성 모듈 | TTL | 용도 | 확인 명령 |
|---|---|---|---|---|
| `vix:current` | vix_fetcher.py | 3600초(1시간) | VIX 현재값 캐시 | `redis-cli GET "vix:current"` |
| `indicators:latest` | 각 indicator 모듈 | 다양 | 기술 지표 최신값 | `redis-cli GET "indicators:latest" \| python3 -m json.tool \| head -10` |

---

## 키 상태 일괄 점검 스크립트

```bash
#!/bin/bash
echo "=== Redis 뉴스 사이클 키 점검 ==="
echo ""

echo "[뉴스 파이프라인]"
echo -n "  latest_titles: "; redis-cli TTL "news:latest_titles"
echo -n "  classified:    "; redis-cli GET "news:classified_latest" 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{len(d)}건')" 2>/dev/null || echo "없음"
echo -n "  summary:       "; redis-cli EXISTS "news:latest_summary"
echo ""

echo "[센티넬]"
echo -n "  watch:    "; redis-cli GET "sentinel:watch" 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{len(d)}건')" 2>/dev/null || echo "없음"
echo -n "  priority: "; redis-cli GET "sentinel:priority" 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{len(d)}건')" 2>/dev/null || echo "없음"
echo ""

echo "[분석]"
echo -n "  comprehensive: "; redis-cli TTL "analysis:comprehensive_report"
echo -n "  emergency:     "; redis-cli TTL "analysis:emergency_report"
echo ""

echo "[시장 데이터]"
echo -n "  VIX: "; redis-cli GET "vix:current" || echo "없음"
echo ""
echo "=== 점검 완료 ==="
```

---

## 키 라이프사이클 타임라인

```
T+0분    뉴스 파이프라인 시작
T+3분    news:latest_titles 갱신 (TTL 5분)
T+5분    news:classified_latest 갱신 (TTL 24시간, 누적)
T+6분    news:key_latest 갱신 (TTL 24시간)
T+8분    Layer 1 완료 → Layer 2 시작
T+10분   analysis:comprehensive_report 갱신 (TTL 2시간)
         continuous_analysis:latest 갱신 (TTL 2시간)
...
T+60분   다음 사이클 시작

센티넬 (독립):
T+0초    detect_anomalies → 이상 없음
T+120초  detect_anomalies → watch 감지 → sentinel:watch 누적
T+240초  detect_anomalies → urgent 감지 → Sonnet → next_cycle → sentinel:priority 누적
T+360초  detect_anomalies → urgent 감지 → Sonnet → emergency → Opus 3+1 팀
         → analysis:emergency_report (TTL 5분)
```

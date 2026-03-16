# 연속 분석 체크리스트 — Layer 1 (Sonnet) + Layer 2 (Opus 3+1)

## 분석 흐름도

```
[60분 주기 — continuous_analysis.py]

_execute_iteration():
  ├── _run_news_pipeline()        ← 01번 체크리스트 참조
  ├── _refresh_sector_rotation()  ← 섹터 ETF 시세 조회 → 회피 섹터 갱신
  └── _run_single_analysis()
        ├── _build_analysis_context()  ← VIX, 레짐, 포지션, 뉴스 요약, 매크로 데이터
        │
        ├── Layer 1: ComprehensiveTeam.analyze()
        │   → 🤖 Sonnet × 4 병렬
        │   ├── NEWS_ANALYST
        │   ├── MACRO_STRATEGIST
        │   ├── RISK_MANAGER
        │   └── SHORT_TERM_TRADER
        │   → dict[str, str] (에이전트별 분석 텍스트)
        │
        ├── _gather_market_context()  ← sentinel:priority, sentinel:watch 포함
        │
        └── Layer 2: opus_team_judgment()
            → 🤖 Opus × 4
            Phase 1 — 3명 독립 병렬 판단:
            ├── 공격형 (confidence >= 0.6)
            ├── 균형형 (confidence >= 0.7)
            └── 보수형 (confidence >= 0.85, 거부권)
            Phase 2 — 리더 종합:
            └── ComprehensiveReport
            → Redis: analysis:comprehensive_report (TTL 2시간)
```

---

## 분석 컨텍스트 빌드

### 확인 로그
```bash
grep -E "VIX|레짐|포지션 조회|Redis 캐시 읽기" logs/trading_system.log | tail -10
```

### 체크 항목
- [ ] VIX 값이 폴백(20.0)이 아닌 실제 값인가?
- [ ] 레짐 판별 결과가 합리적인가? (bull/bear/sideways/volatile)
- [ ] 포지션 목록이 실제와 일치하는가?
- [ ] 뉴스 요약 (`news:latest_summary`)이 비어있지 않은가?

### Redis 확인
```bash
# VIX 캐시
redis-cli GET "vix:current"

# 최근 뉴스 요약
redis-cli GET "news:latest_summary" | python3 -m json.tool | head -10

# 지표 캐시
redis-cli GET "indicators:latest" | python3 -m json.tool | head -10
```

### 이상 징후
| 증상 | 원인 | 대응 |
|---|---|---|
| VIX=20.0 | FRED API 실패 / Redis 캐시 만료 | `redis-cli GET "vix:current"` 확인 |
| "레짐 판별 실패" | VIX 값 문제 / RegimeDetector 장애 | 기본값 sideways 사용됨 |
| 포지션 0건 | PositionMonitor 미동기화 | `curl localhost:9501/api/positions` 확인 |
| 뉴스 요약 "분석 데이터 없음" | 뉴스 파이프라인 미실행 / 캐시 만료 | 01번 체크리스트로 파이프라인 확인 |

---

## 섹터 로테이션 갱신

### 확인 로그
```bash
grep -E "섹터 로테이션" logs/trading_system.log | tail -5
```

### 정상 패턴
```
섹터 로테이션 갱신: top3=['XLK', 'XLY', 'XLF'], avoid=['XLU', 'XLE']
```

### 체크 항목
- [ ] 7개 섹터 ETF 시세가 모두 조회되었는가?
- [ ] top3/avoid 결과가 합리적인가?
- [ ] "섹터 로테이션 갱신 실패" 로그가 없는가?

---

## Layer 1: Sonnet 4에이전트 병렬 분석

### 확인 로그
```bash
grep -E "에이전트 (완료|실패)|Layer 1 완료" logs/trading_system.log | tail -10
```

### 정상 패턴
```
에이전트 완료: NEWS_ANALYST
에이전트 완료: MACRO_STRATEGIST
에이전트 완료: RISK_MANAGER
에이전트 완료: SHORT_TERM_TRADER
Layer 1 완료: 4 에이전트 분석
```

### 체크 항목
- [ ] 4개 에이전트 모두 "완료" 로그가 있는가?
- [ ] "에이전트 실패" 로그가 없는가?
- [ ] 4개가 거의 동시에 완료되는가? (병렬 실행 확인)
- [ ] 각 에이전트 응답이 JSON 형태인가? (raw_response 폴백이 아닌가?)

### 소요 시간 측정
```bash
# Layer 1 시작~완료 시간 차이 확인
grep -E "에이전트 (완료|실패)|Layer 1" logs/trading_system.log | tail -10
```
- 정상: 15~30초 (병렬이므로 가장 느린 에이전트 기준)
- 주의: 60초 이상이면 Sonnet API 응답 지연

### 이상 징후
| 증상 | 원인 | 대응 |
|---|---|---|
| 에이전트 1~2개만 완료 | Sonnet API 부분 장애 | 실패 에이전트 에러 로그 확인 |
| 4개 순차 완료 (시간차 큼) | asyncio.gather 미작동 | 코드 확인: `asyncio.gather(*tasks)` |
| "raw_response" 폴백 | JSON 파싱 실패 | Sonnet 응답 형식 확인 |
| 전체 실패 | API 키 만료 / 네트워크 장애 | `curl anthropic API` 직접 테스트 |

---

## Layer 2: Opus 3+1 팀 최종 판단

### 확인 로그
```bash
grep -E "Opus 팀|Phase [12]|confidence|risk_level" logs/trading_system.log | tail -15
```

### 정상 패턴
```
Opus 팀 Phase 1: 3명 독립 분석 시작
Opus 팀 Phase 2: 리더 종합 시작
Opus 팀 판단 완료: confidence=0.XX, risk=medium, signals=X
Layer 2 완료: confidence=0.XX
```

### 체크 항목

#### Phase 1 — 3명 독립 판단
- [ ] 공격형/균형형/보수형 3명 모두 응답했는가?
- [ ] 3명이 거의 동시에 응답했는가? (병렬 확인)
- [ ] 각 분석가의 action이 JSON에 포함되어 있는가?
- [ ] "Opus XX 분석가 실패" 로그가 없는가?

#### Phase 2 — 리더 종합
- [ ] confidence 값이 0.0~1.0 범위인가?
- [ ] risk_level이 low/medium/high/critical 중 하나인가?
- [ ] signals 배열이 비어있지 않은가?
- [ ] recommendations가 한국어로 구체적인가?

#### 투표 규칙 검증 (코드로 강제됨)
- [ ] **CR-1 confidence 강제**: 공격형 < 0.6, 균형형 < 0.7, 보수형 < 0.85면 hold 강제 확인
- [ ] **거부권**: 보수형 risk_assessment=critical → 리더 호출 없이 즉시 hold (로그: "보수형 거부권 발동")
- [ ] **3명 불일치**: buy/sell/hold 각 1명 → 즉시 hold (로그: "3명 분석가 의견 불일치")
- [ ] **만장일치**: confidence 보정 (로그: "만장일치 confidence 보정")
- [ ] **리더 사후 검증**: 만장일치인데 리더가 뒤집으면 confidence 하한 0.5 적용

### Redis 결과 확인
```bash
redis-cli GET "analysis:comprehensive_report" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'신뢰도: {d.get(\"confidence\", \"?\")}')
print(f'위험도: {d.get(\"risk_level\", \"?\")}')
print(f'신호 수: {len(d.get(\"signals\", []))}')
for s in d.get('signals', [])[:3]:
    print(f'  → {s.get(\"action\")} {s.get(\"ticker\")} : {s.get(\"reason\", \"\")[:50]}')"
```

### 소요 시간
- Phase 1 (3명 병렬): 20~40초
- Phase 2 (리더 1명): 10~20초
- 전체: 30~60초
- 주의: 90초 이상이면 Opus API 지연

### 이상 징후
| 증상 | 원인 | 대응 |
|---|---|---|
| Phase 1에서 1~2명만 응답 | Opus API 부분 장애 | 실패 분석가 fallback=hold 확인 |
| "Opus 리더 판단 실패" | Phase 2 JSON 파싱 실패 | confidence=0.3, risk=high 폴백 확인 |
| confidence가 항상 0.3~0.4 | 리더 판단 실패 반복 | Opus 프롬프트/응답 확인 |
| signals가 항상 hold | 3명 의견 불일치 | 각 분석가 응답 로그 확인 |
| "CR-1 강제" 로그 반복 | 분석가가 낮은 confidence 반환 | 프롬프트/시장 데이터 확인 |
| "보수형 거부권 발동" 과다 | 보수형이 과도하게 critical 판정 | 보수형 프롬프트 기준 조정 |
| "투표 규칙 오버라이드" | 코드 강제 작동 중 | 정상 — 로그에서 reason 확인 |

---

## 센티넬 연계 확인

### 체크 항목
- [ ] `sentinel:priority` 데이터가 분석 컨텍스트에 포함되었는가?
- [ ] `sentinel:watch` 데이터가 분석 컨텍스트에 포함되었는가?

### Redis 확인
```bash
# 센티넬 우선 반영 데이터
redis-cli GET "sentinel:priority" | python3 -m json.tool | head -10
redis-cli GET "sentinel:watch" | python3 -m json.tool | head -10
```

---

## 분석 루프 종합

### 정상 완료 패턴
```bash
grep -E "분석 #[0-9]+ 완료|연속 분석 루프 종료" logs/trading_system.log | tail -5
```

기대:
```
분석 #1 완료 (이슈 2건, 누적 2건)
분석 #2 완료 (이슈 1건, 누적 3건)
```

### 전체 사이클 시간
```bash
# 분석 반복 시작~완료 사이의 시간
grep "분석 #" logs/trading_system.log | tail -5
```
- 정상: 5~15분 (뉴스 파이프라인 + Layer 1 + Layer 2)
- 나머지 45~55분은 대기 (`_wait_or_shutdown`)

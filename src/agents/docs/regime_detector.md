# RegimeDetector

## 역할
VIX 지수와 뉴스 신호, 시장 데이터를 종합하여 현재 시장 레짐(strong_bull/mild_bull/sideways/mild_bear/crash)을 판단한다. VIX 기반 1차 분류 후 Claude Opus로 종합 판단을 수행한다.

## 소속팀
분석팀 (Analysis Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| strong_bull | VIX 0~15 | 강한 강세장 |
| mild_bull | VIX 15~20 | 완만한 강세장 |
| sideways | VIX 20~25 | 횡보장 |
| mild_bear | VIX 25~35 | 완만한 약세장 |
| crash | VIX 35+ | 급락/위기장 |
| Claude 모델 | Opus | 종합 판단 (정확도 최우선) |
| 결과 저장 | data/regime.json | 레짐 상태 영속화 |

## 동작 흐름
1. `detect(vix, market_data, recent_signals)` 호출
2. VIX 범위로 1차 레짐 분류 (`_REGIME_VIX_RANGES` 기준)
3. `build_regime_detection_prompt()` 로 Claude Opus 프롬프트 생성
4. Claude Opus 호출 (`regime_detection` 태스크 타입)
5. AI 종합 판단으로 최종 레짐 결정
6. 이전 레짐과 비교하여 변경 시 로그 생성
7. `current_regime` 속성 업데이트 및 `regime.json` 저장

## 입력
- `vix`: 현재 VIX 지수 (float)
- `market_data`: S&P500, 나스닥, 국채 10년물 등 주요 지표
- `recent_signals`: 최근 분류된 뉴스 신호 목록

## 출력
- `regime`: 시장 레짐 이름 (5가지 중 하나)
- `vix`: 현재 VIX 값
- `confidence`: 판단 신뢰도
- `reason`: 판단 근거
- `changed`: 이전 레짐에서 변경 여부

## 의존성
- `ClaudeClient`: Claude Opus API 호출
- `data/regime.json`: 레짐 상태 영속화

## 소스 파일
`src/analysis/regime/regime_detector.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

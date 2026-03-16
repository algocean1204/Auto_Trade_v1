# EntryStrategy

## 역할
Claude AI 매매 판단과 기술적 지표 종합 신호를 결합하여 최종 진입 후보 목록을 생성한다. 레짐별 포지션 크기, Bull/Inverse 방향 결정, MIN_CONFIDENCE 필터링을 수행한다.

## 소속팀
의사결정팀 (Decision Team)

## 핵심 파라미터
| 파라미터 | 값 | 설명 |
|---|---|---|
| MIN_CONFIDENCE | 0.7 | 진입 후보 최소 신뢰도 임계값 |
| strong_bull 포지션 크기 | 100% | 레짐별 포지션 크기 배수 |
| mild_bull 포지션 크기 | 80% | 레짐별 포지션 크기 배수 |
| sideways 포지션 크기 | 50% | 레짐별 포지션 크기 배수 |
| mild_bear 포지션 크기 | 60% | 역방향(Inverse) 포지션 |
| crash 포지션 크기 | 0% | 신규 매수 전면 차단 |
| 방향 일치 보너스 | +0.1 | 기술적 지표와 Claude 방향 일치 시 신뢰도 보너스 |
| 종목당 최대 | 15% | 전체 포트폴리오 대비 최대 비중 |
| 전체 최대 | 80% | 총 포지션 최대 비중 |

## 동작 흐름
1. Claude 판단에서 buy/sell 추천 추출
2. 기술적 지표와 방향 일치 확인 (일치 시 +0.1 보너스)
3. `MIN_CONFIDENCE (0.7)` 이상인 후보만 필터링
4. 레짐별 포지션 크기 배수 적용
5. crash 레짐이면 신규 진입 전면 차단
6. 종목당 15%, 전체 80% 한도로 포지션 크기 계산
7. Bull 2X ETF vs Inverse 2X ETF 방향 결정
8. 최종 진입 후보 목록 반환

## 입력
- `trading_decisions`: Claude AI 판단 결과 리스트
- `indicator_signals`: 종목별 기술적 지표 종합 결과
- `regime`: 현재 시장 레짐
- `portfolio`: 현재 포트폴리오 상태
- `vix`: 현재 VIX 지수

## 출력
- 진입 후보 목록, 각 항목:
  - `ticker`: 실제 매수할 ETF 심볼 (Bull/Inverse 결정 후)
  - `side`: "buy"
  - `quantity`: 주문 수량
  - `confidence`: 최종 신뢰도
  - `reason`: 진입 근거

## 의존성
- `StrategyParams`: 전략 파라미터 (신뢰도, 포지션 한도 등)
- `MarketHours`: 시장 시간 확인 (정규장 여부)
- `ETF Universe (BULL_2X_UNIVERSE, BEAR_2X_UNIVERSE)`: ETF 유니버스

## 소스 파일
`src/strategy/entry/entry_strategy.py`

## 상태
- 활성: ✅
- 마지막 실행: (자동 업데이트)

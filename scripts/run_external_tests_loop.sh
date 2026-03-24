#!/bin/bash
# 외부 데이터 소스 테스트 무한 반복 스크립트이다.
# 단위 테스트 + 통합 테스트 + 라이브 API 테스트를 반복 실행한다.
# 실패 시 로그에 기록하고 계속 진행한다.

cd /Users/kimtaekyu/Documents/Develop_Fold/Secret_Project/Stock_Trading

LOG_DIR="logs/test_runs"
mkdir -p "$LOG_DIR"

ITERATION=0
PASS_COUNT=0
FAIL_COUNT=0

echo "=========================================="
echo "  외부 데이터 소스 무한 테스트 시작"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

while true; do
    ITERATION=$((ITERATION + 1))
    TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')
    LOG_FILE="$LOG_DIR/test_run_${TIMESTAMP}.log"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  [Iteration #$ITERATION] $(date '+%H:%M:%S')"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Phase 1: 단위 테스트 (mock 기반, 네트워크 불필요)
    echo "  [Phase 1/3] Unit tests..."
    .venv/bin/python -m pytest \
        tests/unit/test_consensus_parsers.py \
        tests/unit/test_polymarket_fetcher.py \
        tests/unit/test_tradingeconomics_fetcher.py \
        tests/unit/test_etf_flow_fetcher.py \
        tests/unit/test_macrotrends_fetcher.py \
        tests/unit/test_tipranks_fetcher.py \
        tests/unit/test_dataroma_fetcher.py \
        --tb=short -q 2>&1 | tee -a "$LOG_FILE"
    UNIT_EXIT=${PIPESTATUS[0]}

    # Phase 2: 통합 테스트 (DI, 캐시 라이프사이클, 데이터 흐름)
    echo "  [Phase 2/3] Integration tests..."
    .venv/bin/python -m pytest \
        tests/integration/test_external_integration.py \
        --tb=short -q 2>&1 | tee -a "$LOG_FILE"
    INTEG_EXIT=${PIPESTATUS[0]}

    # Phase 3: 라이브 API 테스트 (실제 네트워크 요청)
    echo "  [Phase 3/3] Live API tests..."
    .venv/bin/python -m pytest \
        tests/integration/test_external_live_api.py \
        --tb=short -q 2>&1 | tee -a "$LOG_FILE"
    LIVE_EXIT=${PIPESTATUS[0]}

    # 결과 집계
    if [ $UNIT_EXIT -eq 0 ] && [ $INTEG_EXIT -eq 0 ] && [ $LIVE_EXIT -eq 0 ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
        echo "  ✅ ALL PASSED (Unit=$UNIT_EXIT, Integration=$INTEG_EXIT, Live=$LIVE_EXIT)"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "  ❌ FAILURE DETECTED (Unit=$UNIT_EXIT, Integration=$INTEG_EXIT, Live=$LIVE_EXIT)"
        echo "  Log: $LOG_FILE"
    fi

    echo "  📊 누적: $PASS_COUNT passed / $FAIL_COUNT failed / $ITERATION total"

    # 10분 대기 (라이브 API rate limit 방지)
    echo "  ⏳ 다음 실행까지 10분 대기..."
    sleep 600
done

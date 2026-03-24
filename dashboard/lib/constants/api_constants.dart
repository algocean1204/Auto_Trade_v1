/// V2 백엔드 API 관련 타임아웃 및 엔드포인트 경로 상수를 정의한다.
///
/// 모든 경로는 /api/ 프리픽스를 포함한 완전한 경로이다.
/// api_service.dart 에서 참조하며, 동일한 의미의 값이
/// 여러 곳에 중복될 때만 이 파일에 추가한다.
class ApiConstants {
  ApiConstants._();

  // ── 타임아웃 상수 ──

  /// 일반 HTTP 요청 타임아웃 (api_service.dart _timeout 참조).
  static const defaultTimeout = Duration(seconds: 15);

  /// AI 분석·EOD 시퀀스처럼 시간이 오래 걸리는 요청의 타임아웃.
  /// getStockAnalysis, stopTrading 에서 공통으로 사용한다.
  static const longTimeout = Duration(seconds: 120);

  /// 뉴스 수집 파이프라인(크롤링+분류+번역+전송)처럼 매우 오래 걸리는 요청의 타임아웃.
  /// MLX 분류(기사당 3회) + 번역 + Claude 정밀분석 → 최소 8~15분 소요된다.
  static const crawlTimeout = Duration(seconds: 900);

  // ── Dashboard 엔드포인트 ──

  static const dashboardSummary = '/api/dashboard/summary';
  static const dashboardPositions = '/api/dashboard/positions';
  static const dashboardAccounts = '/api/dashboard/accounts';
  static const dashboardTradesRecent = '/api/dashboard/trades/recent';
  static const dashboardChartsDaily = '/api/dashboard/charts/daily-returns';
  static const dashboardChartsCumulative = '/api/dashboard/charts/cumulative';
  static const dashboardChartsHeatmapTicker =
      '/api/dashboard/charts/heatmap/ticker';
  static const dashboardChartsHeatmapHourly =
      '/api/dashboard/charts/heatmap/hourly';
  static const dashboardChartsDrawdown = '/api/dashboard/charts/drawdown';

  // ── Trading 엔드포인트 ──

  static const tradingStatus = '/api/trading/status';
  static const tradingStart = '/api/trading/start';
  static const tradingStop = '/api/trading/stop';

  // ── News 엔드포인트 ──

  static const newsDates = '/api/news/dates';
  static const newsDaily = '/api/news/daily';
  static const newsSummary = '/api/news/summary';
  static const newsCollectAndSend = '/api/news/collect-and-send';
  // /api/news/{article_id} 는 동적 경로이므로 상수로 정의하지 않는다.

  // ── Analysis 엔드포인트 ──

  static const analysisTickers = '/api/analysis/tickers';
  // /api/analysis/comprehensive/{ticker} 는 동적 경로이다.
  // /api/analysis/ticker-news/{ticker} 는 동적 경로이다.

  // ── FX 엔드포인트 ──

  static const fxStatus = '/api/fx/status';
  static const fxHistory = '/api/fx/history';

  // ── Emergency 엔드포인트 ──

  static const emergencyStatus = '/api/emergency/status';
  static const emergencyStop = '/api/emergency/stop';
  static const emergencyResume = '/api/emergency/resume';

  // ── Benchmark 엔드포인트 ──

  static const benchmarkComparison = '/api/benchmark/comparison';
  static const benchmarkChart = '/api/benchmark/chart';

  // ── Macro 엔드포인트 ──

  static const macroCalendar = '/api/macro/calendar';
  static const macroRateOutlook = '/api/macro/rate-outlook';
  static const macroRichIndicators = '/api/macro/indicators/rich';
  // /api/macro/history/{seriesId} 는 동적 경로이다.

  // ── Universe 엔드포인트 ──

  static const universe = '/api/universe';
  static const universeSectors = '/api/universe/sectors';
  static const universeAdd = '/api/universe/add';
  static const universeToggle = '/api/universe/toggle';
  static const universeMappings = '/api/universe/mappings';
  static const universeMappingsAdd = '/api/universe/mappings/add';
  static const universeAutoAdd = '/api/universe/auto-add';
  // /api/universe/{ticker} 는 동적 경로이다.

  // ── Indicators 엔드포인트 ──

  static const indicatorWeights = '/api/indicators/weights';
  // /api/indicators/rsi/{ticker} 는 동적 경로이다.

  // ── Trade Reasoning 엔드포인트 ──

  static const tradeReasoningDates = '/api/trade-reasoning/dates';
  static const tradeReasoningDaily = '/api/trade-reasoning/daily';
  static const tradeReasoningStats = '/api/trade-reasoning/stats';

  // ── Principles 엔드포인트 ──

  static const principles = '/api/principles';
  static const principlesCore = '/api/principles/core';
  // /api/principles/{id} 는 동적 경로이다.

  // ── Manual 엔드포인트 ──

  static const manualAnalyze = '/api/manual/analyze';
  static const manualExecute = '/api/manual/execute';

  // ── Strategy 엔드포인트 ──

  static const strategyParams = '/api/strategy/params';

  // ── Feedback 엔드포인트 ──

  static const feedbackLatest = '/api/feedback/latest';
  // /api/feedback/daily/{date} 는 동적 경로이다.

  // ── System 엔드포인트 ──

  static const systemHealth = '/api/system/health';
  static const systemStatus = '/api/system/status';
  static const systemInfo = '/api/system/info';

  // ── Agents 엔드포인트 ──

  static const agents = '/api/agents';
  // /api/agents/{agent_id} 는 동적 경로이다.

  // ── Health check 엔드포인트 ──

  static const health = '/api/system/health';

  // ── WebSocket 채널명 (ws://host:8000/ws/{channel}) ──

  /// 대시보드 요약 실시간 채널이다.
  static const wsDashboard = 'dashboard';

  /// 포지션 실시간 채널이다.
  static const wsPositions = 'positions';

  /// 체결 내역 실시간 채널이다.
  static const wsTrades = 'trades';

  /// 알림 실시간 채널이다.
  static const wsAlerts = 'alerts';

  /// 오더플로우(스캘퍼 테이프) 실시간 채널이다.
  static const wsOrderflow = 'orderflow';
}

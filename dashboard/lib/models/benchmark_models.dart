// 벤치마크 비교 관련 데이터 모델이다.
//
// /benchmark/comparison 응답 구조:
// {
//   "periods": [{
//     "date": "2026-02-18",
//     "ai_return_pct": float,
//     "spy_return_pct": float,
//     "sso_return_pct": float,
//     "ai_vs_spy_diff": float,
//     "ai_vs_sso_diff": float,
//   }, ...],
//   "summary": {
//     "ai_total": float,
//     "spy_total": float,
//     "sso_total": float,
//     "ai_win_rate_vs_spy": float,
//     "ai_win_rate_vs_sso": float,
//   }
// }
//
// /benchmark/chart 응답 구조 (리스트):
// [{
//   "date": "2026-02-18",
//   "ai_return_pct": float,
//   "spy_return_pct": float,
//   "sso_return_pct": float,
//   "ai_vs_spy_diff": float,
//   "ai_vs_sso_diff": float,
// }, ...]

class BenchmarkSummary {
  final double aiTotal;
  final double spyTotal;
  final double ssoTotal;
  final double aiWinRateVsSpy;
  final double aiWinRateVsSso;

  BenchmarkSummary({
    required this.aiTotal,
    required this.spyTotal,
    required this.ssoTotal,
    required this.aiWinRateVsSpy,
    required this.aiWinRateVsSso,
  });

  factory BenchmarkSummary.fromJson(Map<String, dynamic> json) {
    return BenchmarkSummary(
      aiTotal: (json['ai_total'] as num? ?? 0).toDouble(),
      spyTotal: (json['spy_total'] as num? ?? 0).toDouble(),
      ssoTotal: (json['sso_total'] as num? ?? 0).toDouble(),
      aiWinRateVsSpy: (json['ai_win_rate_vs_spy'] as num? ?? 0).toDouble(),
      aiWinRateVsSso: (json['ai_win_rate_vs_sso'] as num? ?? 0).toDouble(),
    );
  }

  factory BenchmarkSummary.empty() {
    return BenchmarkSummary(
      aiTotal: 0,
      spyTotal: 0,
      ssoTotal: 0,
      aiWinRateVsSpy: 0,
      aiWinRateVsSso: 0,
    );
  }
}

class BenchmarkComparison {
  final List<BenchmarkPeriod> periods;
  final BenchmarkSummary summary;

  BenchmarkComparison({
    required this.periods,
    required this.summary,
  });

  factory BenchmarkComparison.fromJson(Map<String, dynamic> json) {
    final rawPeriods = json['periods'] as List? ?? [];
    return BenchmarkComparison(
      periods: rawPeriods
          .map((p) => BenchmarkPeriod.fromJson(p as Map<String, dynamic>))
          .toList(),
      summary: json['summary'] != null
          ? BenchmarkSummary.fromJson(json['summary'] as Map<String, dynamic>)
          : BenchmarkSummary.empty(),
    );
  }
}

class BenchmarkPeriod {
  final String date;
  final double aiReturnPct;
  final double spyReturnPct;
  final double ssoReturnPct;
  final double aiVsSpyDiff;
  final double aiVsSsoDiff;

  BenchmarkPeriod({
    required this.date,
    required this.aiReturnPct,
    required this.spyReturnPct,
    required this.ssoReturnPct,
    required this.aiVsSpyDiff,
    required this.aiVsSsoDiff,
  });

  factory BenchmarkPeriod.fromJson(Map<String, dynamic> json) {
    return BenchmarkPeriod(
      date: json['date'] as String? ?? '',
      aiReturnPct: (json['ai_return_pct'] as num? ?? 0).toDouble(),
      spyReturnPct: (json['spy_return_pct'] as num? ?? 0).toDouble(),
      ssoReturnPct: (json['sso_return_pct'] as num? ?? 0).toDouble(),
      aiVsSpyDiff: (json['ai_vs_spy_diff'] as num? ?? 0).toDouble(),
      aiVsSsoDiff: (json['ai_vs_sso_diff'] as num? ?? 0).toDouble(),
    );
  }
}

// /benchmark/chart 엔드포인트 응답 항목이다.
// 백엔드는 ai_return_pct, spy_return_pct, sso_return_pct 필드를 반환한다.
class BenchmarkChartPoint {
  final DateTime date;

  /// AI 전략 일간 수익률 (%)
  final double aiReturnPct;

  /// SPY Buy&Hold 일간 수익률 (%)
  final double spyReturnPct;

  /// SSO Buy&Hold 일간 수익률 (%)
  final double ssoReturnPct;

  /// AI vs SPY 차이 (%)
  final double aiVsSpyDiff;

  /// AI vs SSO 차이 (%)
  final double aiVsSsoDiff;

  BenchmarkChartPoint({
    required this.date,
    required this.aiReturnPct,
    required this.spyReturnPct,
    required this.ssoReturnPct,
    required this.aiVsSpyDiff,
    required this.aiVsSsoDiff,
  });

  factory BenchmarkChartPoint.fromJson(Map<String, dynamic> json) {
    return BenchmarkChartPoint(
      // null-safe 파싱: 잘못된 날짜 문자열이 들어와도 크래시 없이 현재 시각으로 폴백한다.
      date: DateTime.tryParse(json['date'] as String? ?? '') ?? DateTime.now(),
      aiReturnPct: (json['ai_return_pct'] as num? ?? 0).toDouble(),
      spyReturnPct: (json['spy_return_pct'] as num? ?? 0).toDouble(),
      ssoReturnPct: (json['sso_return_pct'] as num? ?? 0).toDouble(),
      aiVsSpyDiff: (json['ai_vs_spy_diff'] as num? ?? 0).toDouble(),
      aiVsSsoDiff: (json['ai_vs_sso_diff'] as num? ?? 0).toDouble(),
    );
  }
}

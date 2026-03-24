// 일간 리포트 관련 데이터 모델이다.

class ReportDate {
  final String date;
  final String id;

  ReportDate({
    required this.date,
    required this.id,
  });

  factory ReportDate.fromJson(Map<String, dynamic> json) {
    return ReportDate(
      date: json['date'] as String? ?? '',
      id: json['id'] as String? ?? json['date'] as String? ?? '',
    );
  }
}

class ReportSummary {
  final int totalTrades;
  final int winningTrades;
  final int losingTrades;
  final double winRate;
  final double totalPnl;
  final double avgPnlPct;
  final double maxWinPct;
  final double maxLossPct;
  final int avgHoldMinutes;

  ReportSummary({
    required this.totalTrades,
    required this.winningTrades,
    required this.losingTrades,
    required this.winRate,
    required this.totalPnl,
    required this.avgPnlPct,
    required this.maxWinPct,
    required this.maxLossPct,
    required this.avgHoldMinutes,
  });

  factory ReportSummary.fromJson(Map<String, dynamic> json) {
    return ReportSummary(
      totalTrades: json['total_trades'] as int? ?? 0,
      winningTrades: json['winning_trades'] as int? ?? 0,
      losingTrades: json['losing_trades'] as int? ?? 0,
      winRate: (json['win_rate'] as num? ?? 0).toDouble(),
      totalPnl: (json['total_pnl'] as num? ?? 0).toDouble(),
      avgPnlPct: (json['avg_pnl_pct'] as num? ?? 0).toDouble(),
      maxWinPct: (json['max_win_pct'] as num? ?? 0).toDouble(),
      maxLossPct: (json['max_loss_pct'] as num? ?? 0).toDouble(),
      avgHoldMinutes: json['avg_hold_minutes'] as int? ?? 0,
    );
  }
}

class TickerBreakdown {
  final int trades;
  final double totalPnl;
  final double avgPnlPct;

  TickerBreakdown({
    required this.trades,
    required this.totalPnl,
    required this.avgPnlPct,
  });

  factory TickerBreakdown.fromJson(Map<String, dynamic> json) {
    return TickerBreakdown(
      trades: json['trades'] as int? ?? 0,
      totalPnl: (json['total_pnl'] as num? ?? 0).toDouble(),
      avgPnlPct: (json['avg_pnl_pct'] as num? ?? 0).toDouble(),
    );
  }
}

class RiskMetrics {
  final double maxDrawdownPct;
  final double sharpeEstimate;
  final double avgConfidence;

  RiskMetrics({
    required this.maxDrawdownPct,
    required this.sharpeEstimate,
    required this.avgConfidence,
  });

  factory RiskMetrics.fromJson(Map<String, dynamic> json) {
    return RiskMetrics(
      maxDrawdownPct: (json['max_drawdown_pct'] as num? ?? 0).toDouble(),
      sharpeEstimate: (json['sharpe_estimate'] as num? ?? 0).toDouble(),
      avgConfidence: (json['avg_confidence'] as num? ?? 0).toDouble(),
    );
  }
}

class IndicatorPerformance {
  final double avgEntryValue;
  final int profitableEntries;
  final int totalEntries;
  final double avgPnlWhenBullish;

  IndicatorPerformance({
    required this.avgEntryValue,
    required this.profitableEntries,
    required this.totalEntries,
    required this.avgPnlWhenBullish,
  });

  factory IndicatorPerformance.fromJson(Map<String, dynamic> json) {
    return IndicatorPerformance(
      avgEntryValue: (json['avg_entry_value'] as num? ?? 0).toDouble(),
      profitableEntries: json['profitable_entries'] as int? ?? 0,
      totalEntries: json['total_entries'] as int? ?? 0,
      avgPnlWhenBullish: (json['avg_pnl_when_bullish'] as num? ?? 0).toDouble(),
    );
  }

  double get winRate =>
      totalEntries > 0 ? profitableEntries / totalEntries * 100 : 0;
}

class IndicatorFeedback {
  final Map<String, IndicatorPerformance> indicators;
  final String? recommendation;

  IndicatorFeedback({
    required this.indicators,
    this.recommendation,
  });

  factory IndicatorFeedback.fromJson(Map<String, dynamic> json) {
    final indicatorsMap = <String, IndicatorPerformance>{};

    // 백엔드는 평탄 Map 구조로 반환한다:
    // {"macd": {...}, "rsi_7": {...}, "recommendation": "..."}
    // 중첩 구조 {"indicators": {...}} 와 평탄 구조 모두 처리한다.
    final rawIndicators = json['indicators'] as Map<String, dynamic>?;

    if (rawIndicators != null) {
      // 중첩 구조: json['indicators']가 있는 경우
      rawIndicators.forEach((key, value) {
        if (value is Map<String, dynamic>) {
          indicatorsMap[key] = IndicatorPerformance.fromJson(value);
        }
      });
    } else {
      // 평탄 구조: json 자체가 indicators + recommendation 혼합 맵인 경우
      // recommendation을 제외한 모든 Map 타입 값을 지표 데이터로 파싱한다
      json.forEach((key, value) {
        if (key != 'recommendation' && value is Map<String, dynamic>) {
          indicatorsMap[key] = IndicatorPerformance.fromJson(value);
        }
      });
    }

    return IndicatorFeedback(
      indicators: indicatorsMap,
      recommendation: json['recommendation'] as String?,
    );
  }
}

class DailyReport {
  final String date;
  final ReportSummary summary;
  final Map<String, TickerBreakdown> byTicker;
  final Map<String, int> byHour;
  final Map<String, int> byExitReason;
  final RiskMetrics riskMetrics;
  final IndicatorFeedback? indicatorFeedback;

  DailyReport({
    required this.date,
    required this.summary,
    required this.byTicker,
    required this.byHour,
    required this.byExitReason,
    required this.riskMetrics,
    this.indicatorFeedback,
  });

  factory DailyReport.fromJson(Map<String, dynamic> json) {
    // byTicker 파싱
    final byTickerMap = <String, TickerBreakdown>{};
    final rawByTicker = json['by_ticker'] as Map<String, dynamic>?;
    if (rawByTicker != null) {
      rawByTicker.forEach((key, value) {
        if (value is Map<String, dynamic>) {
          byTickerMap[key] = TickerBreakdown.fromJson(value);
        }
      });
    }

    // byHour 파싱 (키가 "0"~"23" 형태의 문자열)
    final byHourMap = <String, int>{};
    final rawByHour = json['by_hour'] as Map<String, dynamic>?;
    if (rawByHour != null) {
      rawByHour.forEach((key, value) {
        byHourMap[key] = (value as num? ?? 0).toInt();
      });
    }

    // byExitReason 파싱
    final byExitReasonMap = <String, int>{};
    final rawByExitReason = json['by_exit_reason'] as Map<String, dynamic>?;
    if (rawByExitReason != null) {
      rawByExitReason.forEach((key, value) {
        byExitReasonMap[key] = (value as num? ?? 0).toInt();
      });
    }

    return DailyReport(
      date: json['date'] as String? ?? '',
      summary: ReportSummary.fromJson(
          (json['summary'] as Map<String, dynamic>?) ?? {}),
      byTicker: byTickerMap,
      byHour: byHourMap,
      byExitReason: byExitReasonMap,
      riskMetrics: RiskMetrics.fromJson(
          (json['risk_metrics'] as Map<String, dynamic>?) ?? {}),
      indicatorFeedback: json['indicator_feedback'] != null
          ? IndicatorFeedback.fromJson(
              json['indicator_feedback'] as Map<String, dynamic>)
          : null,
    );
  }
}

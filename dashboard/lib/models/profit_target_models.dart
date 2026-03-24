// Addendum 25: 수익 목표 관련 데이터 모델이다.
//
// /api/target/current 응답 구조 (ProfitTargetManager.get_context() 반환값):
// {
//   "monthly_target_usd": float,         ← 월간 목표 (USD 금액)
//   "month_pnl_usd": float,              ← 현재까지 월간 누적 PnL (USD)
//   "achievement_pct": float,            ← 달성률 (%)
//   "remaining_daily_target_usd": float, ← 남은 일일 목표 (USD)
//   "time_progress": {
//     "year": int,
//     "month": int,
//     "total_days": int,
//     "elapsed_days": int,
//     "remaining_days": int,
//     "remaining_trading_days": int,
//     "time_ratio": float,
//   },
//   "aggression_level": string,
//   "aggression_params": {...},
//   "auto_adjust": bool,
// }
//
// /api/target/monthly PUT 요청:
// {"monthly_target_usd": float}          ← 'target_pct' 아님
//
// /api/target/aggression PUT 요청:
// {"aggression_level": string}           ← 'level' 아님

class TimeProgress {
  final int year;
  final int month;
  final int totalDays;
  final int elapsedDays;
  final int remainingDays;
  final int remainingTradingDays;
  final double timeRatio;

  TimeProgress({
    required this.year,
    required this.month,
    required this.totalDays,
    required this.elapsedDays,
    required this.remainingDays,
    required this.remainingTradingDays,
    required this.timeRatio,
  });

  factory TimeProgress.fromJson(Map<String, dynamic> json) {
    return TimeProgress(
      year: json['year'] as int? ?? DateTime.now().year,
      month: json['month'] as int? ?? DateTime.now().month,
      totalDays: json['total_days'] as int? ?? 30,
      elapsedDays: json['elapsed_days'] as int? ?? 0,
      remainingDays: json['remaining_days'] as int? ?? 30,
      remainingTradingDays: json['remaining_trading_days'] as int? ?? 20,
      timeRatio: (json['time_ratio'] as num? ?? 0).toDouble(),
    );
  }

  factory TimeProgress.empty() {
    return TimeProgress(
      year: DateTime.now().year,
      month: DateTime.now().month,
      totalDays: 30,
      elapsedDays: 0,
      remainingDays: 30,
      remainingTradingDays: 20,
      timeRatio: 0,
    );
  }
}

class ProfitTargetStatus {
  /// 월간 수익 목표 (USD)
  final double monthlyTargetUsd;

  /// 현재까지 월간 누적 PnL (USD)
  final double monthPnlUsd;

  /// 달성률 (%)
  final double achievementPct;

  /// 남은 일일 목표 (USD)
  final double remainingDailyTargetUsd;

  /// 월 시간 진행 정보
  final TimeProgress timeProgress;

  final String aggressionLevel;
  final bool autoAdjust;

  ProfitTargetStatus({
    required this.monthlyTargetUsd,
    required this.monthPnlUsd,
    required this.achievementPct,
    required this.remainingDailyTargetUsd,
    required this.timeProgress,
    required this.aggressionLevel,
    required this.autoAdjust,
  });

  factory ProfitTargetStatus.fromJson(Map<String, dynamic> json) {
    final rawTimeProgress = json['time_progress'];
    return ProfitTargetStatus(
      monthlyTargetUsd:
          (json['monthly_target_usd'] as num? ?? 0).toDouble(),
      monthPnlUsd: (json['month_pnl_usd'] as num? ?? 0).toDouble(),
      achievementPct: (json['achievement_pct'] as num? ?? 0).toDouble(),
      remainingDailyTargetUsd:
          (json['remaining_daily_target_usd'] as num? ?? 0).toDouble(),
      timeProgress: rawTimeProgress is Map<String, dynamic>
          ? TimeProgress.fromJson(rawTimeProgress)
          : TimeProgress.empty(),
      aggressionLevel: json['aggression_level'] as String? ?? 'moderate',
      autoAdjust: json['auto_adjust'] as bool? ?? true,
    );
  }

  factory ProfitTargetStatus.empty() {
    return ProfitTargetStatus(
      monthlyTargetUsd: 0,
      monthPnlUsd: 0,
      achievementPct: 0,
      remainingDailyTargetUsd: 0,
      timeProgress: TimeProgress.empty(),
      aggressionLevel: 'moderate',
      autoAdjust: true,
    );
  }

  // API fallback (의존성 없는 경우) 기본값
  factory ProfitTargetStatus.defaultStatus() {
    return ProfitTargetStatus.empty();
  }
}

/// /api/target/history 응답 항목이다.
/// 백엔드 get_target_history() 반환:
/// {
///   "year": int,
///   "month": int,
///   "target_usd": float,
///   "actual_pnl_usd": float,
///   "achievement_pct": float,
/// }
class MonthlyHistory {
  final int year;
  final int month;

  /// 월간 목표 (USD)
  final double targetUsd;

  /// 실제 PnL (USD)
  final double actualPnlUsd;

  /// 달성률 (%)
  final double achievementPct;

  MonthlyHistory({
    required this.year,
    required this.month,
    required this.targetUsd,
    required this.actualPnlUsd,
    required this.achievementPct,
  });

  bool get achieved => actualPnlUsd >= targetUsd;

  factory MonthlyHistory.fromJson(Map<String, dynamic> json) {
    return MonthlyHistory(
      year: json['year'] as int? ?? DateTime.now().year,
      month: json['month'] as int? ?? 1,
      targetUsd: (json['target_usd'] as num? ?? 0).toDouble(),
      actualPnlUsd: (json['actual_pnl_usd'] as num? ?? 0).toDouble(),
      achievementPct: (json['achievement_pct'] as num? ?? 0).toDouble(),
    );
  }
}

class AggressionConfig {
  final String level;
  final double maxPositionPct;
  final int maxTradesPerDay;
  final double minConfidence;
  final double stopLossPct;
  final String description;

  AggressionConfig({
    required this.level,
    required this.maxPositionPct,
    required this.maxTradesPerDay,
    required this.minConfidence,
    required this.stopLossPct,
    required this.description,
  });

  factory AggressionConfig.fromJson(Map<String, dynamic> json) {
    return AggressionConfig(
      level: json['level'] as String? ?? 'moderate',
      maxPositionPct:
          (json['max_position_pct'] as num? ?? 0.20).toDouble(),
      maxTradesPerDay: json['max_trades_per_day'] as int? ?? 6,
      minConfidence: (json['min_confidence'] as num? ?? 0.65).toDouble(),
      stopLossPct: (json['stop_loss_pct'] as num? ?? -0.05).toDouble(),
      description: json['description'] as String? ?? '',
    );
  }
}

/// /api/target/projection 응답 구조:
/// {
///   "current_pnl_usd": float,
///   "daily_avg_usd": float,
///   "projected_month_end_usd": float,
///   "monthly_target_usd": float,
///   "on_track": bool,
///   "projected_deficit_usd": float,
///   "remaining_daily_target_usd": float,
///   "time_progress": {...},
/// }
class ProfitTargetProjection {
  final double currentPnlUsd;
  final double dailyAvgUsd;
  final double projectedMonthEndUsd;
  final double monthlyTargetUsd;
  final bool onTrack;
  final double projectedDeficitUsd;
  final double remainingDailyTargetUsd;

  ProfitTargetProjection({
    required this.currentPnlUsd,
    required this.dailyAvgUsd,
    required this.projectedMonthEndUsd,
    required this.monthlyTargetUsd,
    required this.onTrack,
    required this.projectedDeficitUsd,
    required this.remainingDailyTargetUsd,
  });

  factory ProfitTargetProjection.fromJson(Map<String, dynamic> json) {
    return ProfitTargetProjection(
      currentPnlUsd: (json['current_pnl_usd'] as num? ?? 0).toDouble(),
      dailyAvgUsd: (json['daily_avg_usd'] as num? ?? 0).toDouble(),
      projectedMonthEndUsd:
          (json['projected_month_end_usd'] as num? ?? 0).toDouble(),
      monthlyTargetUsd:
          (json['monthly_target_usd'] as num? ?? 0).toDouble(),
      onTrack: json['on_track'] as bool? ?? false,
      projectedDeficitUsd:
          (json['projected_deficit_usd'] as num? ?? 0).toDouble(),
      remainingDailyTargetUsd:
          (json['remaining_daily_target_usd'] as num? ?? 0).toDouble(),
    );
  }

  factory ProfitTargetProjection.empty() {
    return ProfitTargetProjection(
      currentPnlUsd: 0,
      dailyAvgUsd: 0,
      projectedMonthEndUsd: 0,
      monthlyTargetUsd: 0,
      onTrack: false,
      projectedDeficitUsd: 0,
      remainingDailyTargetUsd: 0,
    );
  }
}

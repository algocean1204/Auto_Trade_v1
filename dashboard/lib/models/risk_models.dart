// Addendum 26: 리스크 대시보드 관련 데이터 모델이다.
//
// /api/risk/dashboard 응답 구조:
// {
//   "updated_at": ISO8601 string,
//   "gates": [{gate_name, passed, action, message, details}, ...],
//   "risk_budget": {...},
//   "var_indicator": {...},
//   "streak_counter": {...},
//   "concentrations": {
//     "limits": {...},
//     "positions": [{ticker, market_value, weight_pct}, ...],
//   },
//   "trailing_stop": {active, positions},
// }

class RiskDashboardData {
  final List<RiskGateStatus> gates;
  final RiskBudget riskBudget;

  /// 백엔드는 concentrations를 {"limits": {...}, "positions": [...]} 형태로 반환한다.
  final ConcentrationStatus concentrations;

  final VarIndicator varIndicator;
  final TrailingStopStatus trailingStop;
  final StreakCounter streakCounter;
  final DateTime updatedAt;

  RiskDashboardData({
    required this.gates,
    required this.riskBudget,
    required this.concentrations,
    required this.varIndicator,
    required this.trailingStop,
    required this.streakCounter,
    required this.updatedAt,
  });

  factory RiskDashboardData.empty() {
    return RiskDashboardData(
      gates: [],
      riskBudget: RiskBudget(
        totalBudgetPct: 0,
        usedPct: 0,
        remainingPct: 0,
        dailyLimitPct: 0,
        dailyUsedPct: 0,
      ),
      concentrations: ConcentrationStatus.empty(),
      varIndicator: VarIndicator(
        varPct: 0,
        confidenceLevel: 0,
        riskLevel: 'UNKNOWN',
        maxAcceptablePct: 0,
      ),
      trailingStop: TrailingStopStatus(
        active: false,
        stopThresholdPct: 0,
        positions: [],
      ),
      streakCounter: StreakCounter(
        winStreak: 0,
        lossStreak: 0,
        maxWinStreak: 0,
        maxLossStreak: 0,
        currentStreak: 'none',
      ),
      updatedAt: DateTime.now(),
    );
  }

  factory RiskDashboardData.fromJson(Map<String, dynamic> json) {
    try {
      // concentrations 파싱:
      // 백엔드가 {} (빈 맵) 또는 {"limits": {...}, "positions": [...]} 형태로 반환한다
      ConcentrationStatus concentrations;
      final rawConc = json['concentrations'];
      if (rawConc is Map<String, dynamic>) {
        concentrations = ConcentrationStatus.fromJson(rawConc);
      } else {
        concentrations = ConcentrationStatus.empty();
      }

      return RiskDashboardData(
        gates: (json['gates'] as List? ?? [])
            .map((g) => RiskGateStatus.fromJson(g as Map<String, dynamic>))
            .toList(),
        riskBudget: json['risk_budget'] is Map<String, dynamic>
            ? RiskBudget.fromJson(json['risk_budget'] as Map<String, dynamic>)
            : RiskBudget(
                totalBudgetPct: 0,
                usedPct: 0,
                remainingPct: 0,
                dailyLimitPct: 0,
                dailyUsedPct: 0,
              ),
        concentrations: concentrations,
        varIndicator: json['var_indicator'] is Map<String, dynamic>
            ? VarIndicator.fromJson(
                json['var_indicator'] as Map<String, dynamic>)
            : VarIndicator(
                varPct: 0,
                confidenceLevel: 0,
                riskLevel: 'UNKNOWN',
                maxAcceptablePct: 0,
              ),
        trailingStop: json['trailing_stop'] is Map<String, dynamic>
            ? TrailingStopStatus.fromJson(
                json['trailing_stop'] as Map<String, dynamic>)
            : TrailingStopStatus(
                active: false,
                stopThresholdPct: 0,
                positions: [],
              ),
        streakCounter: json['streak_counter'] is Map<String, dynamic>
            ? StreakCounter.fromJson(
                json['streak_counter'] as Map<String, dynamic>)
            : StreakCounter(
                winStreak: 0,
                lossStreak: 0,
                maxWinStreak: 0,
                maxLossStreak: 0,
                currentStreak: 'none',
              ),
        updatedAt: json['updated_at'] != null
            ? (DateTime.tryParse(json['updated_at'] as String) ?? DateTime.now())
            : DateTime.now(),
      );
    } catch (_) {
      return RiskDashboardData.empty();
    }
  }
}

/// 리스크 게이트 상태이다.
/// 백엔드 응답 필드: gate_name, passed, action, message, details
class RiskGateStatus {
  final String gateName;
  final bool passed;
  final String action;
  final String message;
  final Map<String, dynamic> details;

  /// UI 표시용 이름 (백엔드가 반환하지 않으면 gateName에서 생성한다)
  String get displayName => gateName.replaceAll('_', ' ').toUpperCase();

  /// 화면에 표시할 설명 (message 필드를 사용한다)
  String get description => message;

  /// 현재 값 (details 맵에서 추출한다, 없으면 null)
  double? get currentValue {
    final v = details['current_value'] ?? details['value'] ?? details['pct'];
    if (v is num) return v.toDouble();
    return null;
  }

  /// 임계값 (details 맵에서 추출한다, 없으면 null)
  double? get threshold {
    final v = details['threshold'] ?? details['limit'];
    if (v is num) return v.toDouble();
    return null;
  }

  /// UI에서 사용하는 상태 문자열
  String get status => passed ? 'passed' : 'failed';

  RiskGateStatus({
    required this.gateName,
    required this.passed,
    required this.action,
    required this.message,
    required this.details,
  });

  factory RiskGateStatus.fromJson(Map<String, dynamic> json) {
    return RiskGateStatus(
      gateName: json['gate_name'] as String? ?? '',
      passed: json['passed'] as bool? ?? false,
      action: json['action'] as String? ?? '',
      message: json['message'] as String? ?? '',
      details: json['details'] is Map<String, dynamic>
          ? json['details'] as Map<String, dynamic>
          : {},
    );
  }
}

class RiskBudget {
  final double totalBudgetPct;
  final double usedPct;
  final double remainingPct;
  final double dailyLimitPct;
  final double dailyUsedPct;

  // 백엔드 추가 필드
  final double budgetAmountUsd;
  final double totalLossesUsd;
  final double remainingBudgetUsd;
  final int currentTier;
  final double positionScale;

  RiskBudget({
    required this.totalBudgetPct,
    required this.usedPct,
    required this.remainingPct,
    required this.dailyLimitPct,
    required this.dailyUsedPct,
    this.budgetAmountUsd = 0.0,
    this.totalLossesUsd = 0.0,
    this.remainingBudgetUsd = 0.0,
    this.currentTier = 1,
    this.positionScale = 1.0,
  });

  factory RiskBudget.fromJson(Map<String, dynamic> json) {
    // 백엔드 실제 키: budget_pct, consumption_pct, budget_amount_usd,
    // total_losses_usd, remaining_budget_usd, current_tier, position_scale
    final budgetPct = (json['budget_pct'] as num? ?? 0).toDouble().abs();
    final consumptionPct = (json['consumption_pct'] as num? ?? 0).toDouble();

    // totalBudgetPct: budget_pct (절댓값)
    // usedPct: consumption_pct (소비율 %)
    // remainingPct: 100 - consumption_pct
    return RiskBudget(
      totalBudgetPct: budgetPct,
      usedPct: consumptionPct,
      remainingPct: (100.0 - consumptionPct).clamp(0.0, 100.0),
      // 백엔드에 별도 daily 필드가 없으므로 0으로 유지한다
      dailyLimitPct: (json['daily_limit_pct'] as num? ?? 0).toDouble(),
      dailyUsedPct: (json['daily_used_pct'] as num? ?? 0).toDouble(),
      budgetAmountUsd: (json['budget_amount_usd'] as num? ?? 0).toDouble(),
      totalLossesUsd: (json['total_losses_usd'] as num? ?? 0).toDouble(),
      remainingBudgetUsd: (json['remaining_budget_usd'] as num? ?? 0).toDouble(),
      currentTier: json['current_tier'] as int? ?? 1,
      positionScale: (json['position_scale'] as num? ?? 1.0).toDouble(),
    );
  }
}

/// 집중도 현황이다.
/// 백엔드 응답:
/// {
///   "limits": {...},   ← ConcentrationLimiter.get_status() 반환값
///   "positions": [{ticker, market_value, weight_pct}, ...],
/// }
class ConcentrationStatus {
  /// 집중도 한도 설정 (백엔드 get_status() 반환값을 그대로 보관한다)
  final Map<String, dynamic> limits;

  /// 포트폴리오 내 종목별 집중도
  final List<PositionConcentration> positions;

  ConcentrationStatus({
    required this.limits,
    required this.positions,
  });

  factory ConcentrationStatus.fromJson(Map<String, dynamic> json) {
    final rawPositions = json['positions'];
    return ConcentrationStatus(
      limits: json['limits'] is Map<String, dynamic>
          ? json['limits'] as Map<String, dynamic>
          : {},
      positions: rawPositions is List
          ? rawPositions
              .map((p) =>
                  PositionConcentration.fromJson(p as Map<String, dynamic>))
              .toList()
          : [],
    );
  }

  factory ConcentrationStatus.empty() {
    return ConcentrationStatus(limits: {}, positions: []);
  }
}

/// 개별 종목 집중도이다.
/// 백엔드 응답 필드: ticker, market_value, weight_pct
class PositionConcentration {
  final String ticker;

  /// 시장 가치 (USD)
  final double marketValue;

  /// 포트폴리오 내 비중 (%)
  final double weightPct;

  PositionConcentration({
    required this.ticker,
    required this.marketValue,
    required this.weightPct,
  });

  factory PositionConcentration.fromJson(Map<String, dynamic> json) {
    return PositionConcentration(
      ticker: json['ticker'] as String? ?? '',
      marketValue: (json['market_value'] as num? ?? 0).toDouble(),
      weightPct: (json['weight_pct'] as num? ?? 0).toDouble(),
    );
  }
}

class VarIndicator {
  final double varPct;
  final double confidenceLevel;
  final String riskLevel;
  final double maxAcceptablePct;

  // 백엔드 추가 필드
  final int lookbackDays;
  final double zScore;

  VarIndicator({
    required this.varPct,
    required this.confidenceLevel,
    required this.riskLevel,
    required this.maxAcceptablePct,
    this.lookbackDays = 20,
    this.zScore = 1.645,
  });

  factory VarIndicator.fromJson(Map<String, dynamic> json) {
    // 백엔드 실제 키: confidence, lookback_days, max_var_pct, z_score
    // var_pct는 calculate 결과로만 포함되므로 없으면 0.0으로 처리한다
    return VarIndicator(
      varPct: (json['var_pct'] as num? ?? 0).toDouble(),
      // 백엔드 키: confidence (0.0~1.0 비율)
      confidenceLevel: (json['confidence'] as num? ??
              json['confidence_level'] as num? ?? 0)
          .toDouble(),
      // 백엔드는 risk_level 필드를 별도로 반환하지 않는다. 기본값 사용.
      riskLevel: json['risk_level'] as String? ?? 'UNKNOWN',
      // 백엔드 키: max_var_pct
      maxAcceptablePct: (json['max_var_pct'] as num? ??
              json['max_acceptable_pct'] as num? ?? 0)
          .toDouble(),
      lookbackDays: json['lookback_days'] as int? ?? 20,
      zScore: (json['z_score'] as num? ?? 1.645).toDouble(),
    );
  }
}

class TrailingStopStatus {
  final bool active;
  final double? highWaterMark;
  final double? currentDrawdown;
  final double stopThresholdPct;
  final List<TrailingStopPosition> positions;

  // 백엔드 추가 필드
  final double initialStopPct;
  final double trailingStopPct;
  final int trackedPositions;

  TrailingStopStatus({
    required this.active,
    this.highWaterMark,
    this.currentDrawdown,
    required this.stopThresholdPct,
    required this.positions,
    this.initialStopPct = 0.0,
    this.trailingStopPct = 0.0,
    this.trackedPositions = 0,
  });

  factory TrailingStopStatus.fromJson(Map<String, dynamic> json) {
    // 백엔드 실제 키: initial_stop_pct, trailing_stop_pct, tracked_positions,
    // positions (Map<ticker, {entry_price, high_price, stop_price, stop_type}>)
    final trackedPositions = json['tracked_positions'] as int? ?? 0;

    // positions 필드가 Map인 경우 List로 변환한다
    List<TrailingStopPosition> positionList = [];
    final rawPositions = json['positions'];
    if (rawPositions is List) {
      positionList = rawPositions
          .map((p) => TrailingStopPosition.fromJson(p as Map<String, dynamic>))
          .toList();
    } else if (rawPositions is Map) {
      // 백엔드가 {ticker: {entry_price, high_price, stop_price, stop_type}} 형태로 반환한다
      positionList = rawPositions.entries.map((entry) {
        final ticker = entry.key as String;
        final info = entry.value as Map<String, dynamic>? ?? {};
        return TrailingStopPosition.fromJson({'ticker': ticker, ...info});
      }).toList();
    }

    final trailingStopPct =
        (json['trailing_stop_pct'] as num? ?? 0).toDouble();

    return TrailingStopStatus(
      // active: tracked_positions > 0 이면 활성 상태로 판단한다
      active: json['active'] as bool? ?? trackedPositions > 0,
      highWaterMark: json['high_water_mark'] != null
          ? (json['high_water_mark'] as num).toDouble()
          : null,
      currentDrawdown: json['current_drawdown'] != null
          ? (json['current_drawdown'] as num).toDouble()
          : null,
      // trailing_stop_pct를 stopThresholdPct로 매핑한다
      stopThresholdPct: json['stop_threshold_pct'] != null
          ? (json['stop_threshold_pct'] as num).toDouble()
          : trailingStopPct,
      positions: positionList,
      initialStopPct:
          (json['initial_stop_pct'] as num? ?? 0).toDouble(),
      trailingStopPct: trailingStopPct,
      trackedPositions: trackedPositions,
    );
  }
}

class TrailingStopPosition {
  final String ticker;
  final double highPrice;
  final double currentPrice;
  final double drawdownPct;
  final double stopPrice;

  TrailingStopPosition({
    required this.ticker,
    required this.highPrice,
    required this.currentPrice,
    required this.drawdownPct,
    required this.stopPrice,
  });

  factory TrailingStopPosition.fromJson(Map<String, dynamic> json) {
    return TrailingStopPosition(
      ticker: json['ticker'] as String? ?? '',
      highPrice: (json['high_price'] as num? ?? 0).toDouble(),
      currentPrice: (json['current_price'] as num? ?? 0).toDouble(),
      drawdownPct: (json['drawdown_pct'] as num? ?? 0).toDouble(),
      stopPrice: (json['stop_price'] as num? ?? 0).toDouble(),
    );
  }
}

class StreakCounter {
  final int winStreak;
  final int lossStreak;
  final int maxWinStreak;
  final int maxLossStreak;
  final String currentStreak;

  // 백엔드 실제 필드
  final int dailyLossDays;
  final int dailyLossStreakThreshold;
  final Map<String, dynamic> streakRules;

  StreakCounter({
    required this.winStreak,
    required this.lossStreak,
    required this.maxWinStreak,
    required this.maxLossStreak,
    required this.currentStreak,
    this.dailyLossDays = 0,
    this.dailyLossStreakThreshold = 3,
    this.streakRules = const {},
  });

  factory StreakCounter.fromJson(Map<String, dynamic> json) {
    // 백엔드 실제 키: current_streak(int), daily_loss_days(int),
    // streak_rules(dict), daily_loss_streak_threshold(int)
    final currentStreakRaw = json['current_streak'];
    // current_streak이 int로 올 경우 문자열로 변환한다
    final String currentStreakStr = currentStreakRaw is int
        ? (currentStreakRaw > 0
            ? 'win'
            : currentStreakRaw < 0
                ? 'loss'
                : 'none')
        : currentStreakRaw as String? ?? 'none';

    final currentStreakInt = currentStreakRaw is int ? currentStreakRaw : 0;

    return StreakCounter(
      // current_streak(int): 양수=연승, 음수=연패
      winStreak: currentStreakInt > 0 ? currentStreakInt : 0,
      lossStreak: currentStreakInt < 0 ? currentStreakInt.abs() : 0,
      // 백엔드에 max streak 필드가 없으므로 현재 값으로 대체한다
      maxWinStreak: json['max_win_streak'] as int? ??
          (currentStreakInt > 0 ? currentStreakInt : 0),
      maxLossStreak: json['max_loss_streak'] as int? ??
          (currentStreakInt < 0 ? currentStreakInt.abs() : 0),
      currentStreak: currentStreakStr,
      dailyLossDays: json['daily_loss_days'] as int? ?? 0,
      dailyLossStreakThreshold:
          json['daily_loss_streak_threshold'] as int? ?? 3,
      streakRules: json['streak_rules'] is Map<String, dynamic>
          ? json['streak_rules'] as Map<String, dynamic>
          : const {},
    );
  }
}

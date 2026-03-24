// 슬리피지 관련 데이터 모델이다.

class SlippageStats {
  final double avgSlippagePct;
  final double maxSlippagePct;
  // 백엔드 응답에 total_trades / total_slippage_cost 키가 없으므로 기본값 0을 사용한다.
  final int totalTrades;
  final double totalSlippageCost;

  // 백엔드 추가 필드
  final double medianSlippagePct;
  final Map<String, double> byHour;

  SlippageStats({
    required this.avgSlippagePct,
    required this.maxSlippagePct,
    this.totalTrades = 0,
    this.totalSlippageCost = 0.0,
    this.medianSlippagePct = 0.0,
    this.byHour = const {},
  });

  factory SlippageStats.fromJson(Map<String, dynamic> json) {
    // 백엔드 실제 키: avg_slippage_pct, median_slippage_pct, max_slippage_pct, by_hour
    // total_trades / total_slippage_cost 키는 백엔드에 없으므로 0으로 유지한다.
    final rawByHour = json['by_hour'] as Map<String, dynamic>?;
    final byHourMap = <String, double>{};
    if (rawByHour != null) {
      rawByHour.forEach((key, value) {
        if (value is num) byHourMap[key] = value.toDouble();
      });
    }

    return SlippageStats(
      avgSlippagePct: (json['avg_slippage_pct'] as num? ?? 0).toDouble(),
      maxSlippagePct: (json['max_slippage_pct'] as num? ?? 0).toDouble(),
      totalTrades: json['total_trades'] as int? ?? 0,
      totalSlippageCost:
          (json['total_slippage_cost'] as num? ?? 0).toDouble(),
      medianSlippagePct:
          (json['median_slippage_pct'] as num? ?? 0).toDouble(),
      byHour: byHourMap,
    );
  }
}

class OptimalHour {
  final int hour;
  final double avgSlippage;
  final int tradeCount;
  final String recommendation;

  OptimalHour({
    required this.hour,
    required this.avgSlippage,
    required this.tradeCount,
    this.recommendation = '',
  });

  /// 백엔드 SlippageHourEntry 필드명에 맞춤: avg_slippage, trade_count, recommendation
  factory OptimalHour.fromJson(Map<String, dynamic> json) {
    return OptimalHour(
      hour: json['hour'] as int? ?? 0,
      avgSlippage: (json['avg_slippage'] as num? ?? 0).toDouble(),
      tradeCount: json['trade_count'] as int? ?? 0,
      recommendation: json['recommendation'] as String? ?? '',
    );
  }
}

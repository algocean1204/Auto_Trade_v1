// 차트 관련 데이터 모델이다.

class DailyReturn {
  final DateTime date;
  final double pnlAmount;
  final double pnlPct;
  final int tradeCount;

  DailyReturn({
    required this.date,
    required this.pnlAmount,
    required this.pnlPct,
    required this.tradeCount,
  });

  /// 백엔드 daily_returns 캐시 데이터를 파싱한다.
  /// 백엔드는 pnl_amount와 pnl 두 키를 모두 저장한다 (이전 캐시 호환을 위해 pnl 폴백).
  factory DailyReturn.fromJson(Map<String, dynamic> json) {
    return DailyReturn(
      date: json['date'] != null
          ? (DateTime.tryParse(json['date'] as String) ?? DateTime.now())
          : DateTime.now(),
      pnlAmount: (json['pnl_amount'] as num?)?.toDouble()
          ?? (json['pnl'] as num? ?? 0).toDouble(),
      pnlPct: (json['pnl_pct'] as num? ?? 0).toDouble(),
      tradeCount: json['trade_count'] as int? ?? 0,
    );
  }
}

class CumulativeReturn {
  final DateTime date;
  final double cumulativePnl;
  final double cumulativePct;

  CumulativeReturn({
    required this.date,
    required this.cumulativePnl,
    required this.cumulativePct,
  });

  factory CumulativeReturn.fromJson(Map<String, dynamic> json) {
    return CumulativeReturn(
      date: json['date'] != null
          ? (DateTime.tryParse(json['date'] as String) ?? DateTime.now())
          : DateTime.now(),
      cumulativePnl: (json['cumulative_pnl'] as num? ?? 0).toDouble(),
      // cumulative_pct 필드가 없을 경우 0.0을 기본값으로 사용한다
      cumulativePct: json['cumulative_pct'] != null
          ? (json['cumulative_pct'] as num).toDouble()
          : (json['cumulative_return_pct'] != null
              ? (json['cumulative_return_pct'] as num).toDouble()
              : 0.0),
    );
  }
}

class HeatmapPoint {
  final String x;
  final String y;
  final double value;

  HeatmapPoint({
    required this.x,
    required this.y,
    required this.value,
  });

  /// 백엔드 히트맵 데이터 구조에 맞춰 파싱한다.
  /// 티커 히트맵: {ticker, win_rate, trade_count}
  /// 시간대 히트맵: {hour, win_rate, trade_count}
  /// x에 티커명/시간대, value에 승률을 매핑한다.
  factory HeatmapPoint.fromJson(Map<String, dynamic> json) {
    // x: 티커명 또는 시간대 (hour를 문자열로 변환)
    final x = json['x'] as String?
        ?? json['ticker'] as String?
        ?? (json['hour'] != null ? json['hour'].toString() : '');
    // y: 명시적 y 값 또는 거래 횟수를 문자열로 표시
    final y = json['y'] as String?
        ?? (json['trade_count'] != null ? json['trade_count'].toString() : '');
    // value: 명시적 value 또는 승률(win_rate)
    final value = (json['value'] as num?)?.toDouble()
        ?? (json['win_rate'] as num? ?? 0).toDouble();
    return HeatmapPoint(x: x, y: y, value: value);
  }
}

class DrawdownPoint {
  final DateTime date;
  final double peak;
  final double current;
  final double drawdownPct;

  DrawdownPoint({
    required this.date,
    required this.peak,
    required this.current,
    required this.drawdownPct,
  });

  /// 백엔드 drawdown 데이터 구조에 맞춰 파싱한다.
  /// 백엔드는 {date, drawdown_pct}만 저장하므로 peak/current는 0.0 기본값을 사용한다.
  factory DrawdownPoint.fromJson(Map<String, dynamic> json) {
    return DrawdownPoint(
      date: json['date'] != null
          ? (DateTime.tryParse(json['date'] as String) ?? DateTime.now())
          : DateTime.now(),
      peak: (json['peak'] as num? ?? 0).toDouble(),
      current: (json['current'] as num? ?? 0).toDouble(),
      drawdownPct: (json['drawdown_pct'] as num? ?? 0).toDouble(),
    );
  }
}

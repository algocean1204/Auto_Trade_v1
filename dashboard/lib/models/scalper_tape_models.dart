// 스캘퍼 테이프 실시간 데이터 모델이다.
// WebSocket /ws/realtime-tape/{ticker} 엔드포인트에서 수신하는 JSON 구조를 표현한다.

class ObiData {
  /// 오더북 불균형 지수 (-1.0 ~ +1.0). 양수=매수 압력, 음수=매도 압력이다.
  final double value;

  /// 평활화된 OBI 값이다.
  final double smoothed;

  /// 매매 신호이다: "strong_buy", "buy", "neutral", "sell", "strong_sell"
  final String signal;

  const ObiData({
    required this.value,
    required this.smoothed,
    required this.signal,
  });

  factory ObiData.fromJson(Map<String, dynamic> json) {
    return ObiData(
      value: (json['value'] as num? ?? 0).toDouble(),
      smoothed: (json['smoothed'] as num? ?? 0).toDouble(),
      signal: json['signal'] as String? ?? 'neutral',
    );
  }
}

class CvdData {
  /// 누적 거래량 델타이다.
  final double cumulative;

  /// 다이버전스 유형이다: "bullish_divergence", "bearish_divergence", null
  final String? divergence;

  const CvdData({
    required this.cumulative,
    this.divergence,
  });

  factory CvdData.fromJson(Map<String, dynamic> json) {
    return CvdData(
      cumulative: (json['cumulative'] as num? ?? 0).toDouble(),
      divergence: json['divergence'] as String?,
    );
  }
}

class VpinData {
  /// VPIN 값이다 (0.0 ~ 1.0).
  final double value;

  /// 위험 레벨이다: "safe", "warning", "danger", "critical"
  final String level;

  const VpinData({
    required this.value,
    required this.level,
  });

  factory VpinData.fromJson(Map<String, dynamic> json) {
    return VpinData(
      value: (json['value'] as num? ?? 0).toDouble(),
      level: json['level'] as String? ?? 'safe',
    );
  }
}

class ExecutionStrengthData {
  /// 현재 체결 강도 값이다.
  final double current;

  /// 추세이다: "strengthening", "weakening", "stable"
  final String trend;

  /// 서지 여부이다.
  final bool isSurge;

  const ExecutionStrengthData({
    required this.current,
    required this.trend,
    required this.isSurge,
  });

  factory ExecutionStrengthData.fromJson(Map<String, dynamic> json) {
    return ExecutionStrengthData(
      current: (json['current'] as num? ?? 0).toDouble(),
      trend: json['trend'] as String? ?? 'stable',
      isSurge: json['is_surge'] as bool? ?? false,
    );
  }
}

class ToxicityData {
  /// 복합 독성 지수이다 (0.0 ~ 1.0).
  final double composite;

  /// 독성 레벨이다: "safe", "warning", "danger", "blocked"
  final String level;

  /// 거래 잠금 여부이다.
  final bool isLocked;

  /// 잠금 해제까지 남은 시간(초)이다. null이면 잠금 상태가 아니다.
  final double? lockRemaining;

  const ToxicityData({
    required this.composite,
    required this.level,
    required this.isLocked,
    this.lockRemaining,
  });

  factory ToxicityData.fromJson(Map<String, dynamic> json) {
    return ToxicityData(
      composite: (json['composite'] as num? ?? 0).toDouble(),
      level: json['level'] as String? ?? 'safe',
      isLocked: json['is_locked'] as bool? ?? false,
      lockRemaining: json['lock_remaining'] != null
          ? (json['lock_remaining'] as num).toDouble()
          : null,
    );
  }
}

class TimeStopData {
  /// 포지션 진입 후 경과 시간(초)이다.
  final double elapsed;

  /// 타임 스탑까지 남은 시간(초)이다.
  final double remaining;

  /// 권장 액션이다: "hold", "force_exit", "breakeven"
  final String action;

  const TimeStopData({
    required this.elapsed,
    required this.remaining,
    required this.action,
  });

  factory TimeStopData.fromJson(Map<String, dynamic> json) {
    return TimeStopData(
      elapsed: (json['elapsed'] as num? ?? 0).toDouble(),
      remaining: (json['remaining'] as num? ?? 0).toDouble(),
      action: json['action'] as String? ?? 'hold',
    );
  }
}

/// 스캘퍼 테이프 실시간 스냅샷이다.
/// WebSocket 메시지 1개에 대응한다.
class ScalperTapeData {
  final String ticker;
  final DateTime timestamp;
  final ObiData? obi;
  final CvdData? cvd;
  final VpinData? vpin;
  final ExecutionStrengthData? executionStrength;
  final double spreadBps;
  final double lastPrice;
  final int lastVolume;
  final ToxicityData? toxicity;
  final TimeStopData? timeStop;

  const ScalperTapeData({
    required this.ticker,
    required this.timestamp,
    this.obi,
    this.cvd,
    this.vpin,
    this.executionStrength,
    required this.spreadBps,
    required this.lastPrice,
    required this.lastVolume,
    this.toxicity,
    this.timeStop,
  });

  factory ScalperTapeData.fromJson(Map<String, dynamic> json) {
    return ScalperTapeData(
      ticker: json['ticker'] as String? ?? '',
      timestamp: json['timestamp'] != null
          ? DateTime.tryParse(json['timestamp'] as String) ?? DateTime.now()
          : DateTime.now(),
      obi: json['obi'] != null
          ? ObiData.fromJson(json['obi'] as Map<String, dynamic>)
          : null,
      cvd: json['cvd'] != null
          ? CvdData.fromJson(json['cvd'] as Map<String, dynamic>)
          : null,
      vpin: json['vpin'] != null
          ? VpinData.fromJson(json['vpin'] as Map<String, dynamic>)
          : null,
      executionStrength: json['execution_strength'] != null
          ? ExecutionStrengthData.fromJson(
              json['execution_strength'] as Map<String, dynamic>)
          : null,
      spreadBps: (json['spread_bps'] as num? ?? 0).toDouble(),
      lastPrice: (json['last_price'] as num? ?? 0).toDouble(),
      lastVolume: json['last_volume'] as int? ?? 0,
      toxicity: json['toxicity'] != null
          ? ToxicityData.fromJson(json['toxicity'] as Map<String, dynamic>)
          : null,
      timeStop: json['time_stop'] != null
          ? TimeStopData.fromJson(json['time_stop'] as Map<String, dynamic>)
          : null,
    );
  }
}

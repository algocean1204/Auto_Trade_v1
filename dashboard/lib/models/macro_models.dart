// 거시경제 지표 관련 데이터 모델 정의이다.

class MacroIndicators {
  final VixStatus vix;
  final FearGreedIndex fearGreed;
  final FedRate fedRate;
  final CpiData cpi;
  final UnemploymentData unemployment;
  final TreasurySpread treasurySpread;
  final RegimeInfo regime;
  final DateTime updatedAt;

  const MacroIndicators({
    required this.vix,
    required this.fearGreed,
    required this.fedRate,
    required this.cpi,
    required this.unemployment,
    required this.treasurySpread,
    required this.regime,
    required this.updatedAt,
  });

  factory MacroIndicators.fromJson(Map<String, dynamic> json) {
    return MacroIndicators(
      vix: VixStatus.fromJson(json['vix'] as Map<String, dynamic>? ?? {}),
      fearGreed: FearGreedIndex.fromJson(
          json['fear_greed'] as Map<String, dynamic>? ?? {}),
      fedRate:
          FedRate.fromJson(json['fed_rate'] as Map<String, dynamic>? ?? {}),
      cpi: CpiData.fromJson(json['cpi'] as Map<String, dynamic>? ?? {}),
      unemployment: UnemploymentData.fromJson(
          json['unemployment'] as Map<String, dynamic>? ?? {}),
      treasurySpread: TreasurySpread.fromJson(
          json['treasury_spread'] as Map<String, dynamic>? ?? {}),
      regime:
          RegimeInfo.fromJson(json['regime'] as Map<String, dynamic>? ?? {}),
      updatedAt: json['updated_at'] != null
          ? DateTime.tryParse(json['updated_at'].toString()) ?? DateTime.now()
          : DateTime.now(),
    );
  }

  /// 백엔드 연결 전 사용할 기본값 팩토리이다.
  factory MacroIndicators.empty() {
    return MacroIndicators(
      vix: VixStatus(value: 0, change1d: 0, level: 'neutral'),
      fearGreed: FearGreedIndex(score: 50, label: 'Neutral', description: ''),
      fedRate: FedRate(value: 0, targetRange: 'N/A'),
      cpi: CpiData(value: 0),
      unemployment: UnemploymentData(value: 0),
      treasurySpread: TreasurySpread(value: 0, signal: 'normal'),
      regime: RegimeInfo(current: 'unknown', confidence: 0),
      updatedAt: DateTime.now(),
    );
  }
}

class VixStatus {
  final double value;
  final double change1d;
  /// "extreme_fear", "fear", "neutral", "greed", "extreme_greed"
  final String level;

  const VixStatus({
    required this.value,
    required this.change1d,
    required this.level,
  });

  factory VixStatus.fromJson(Map<String, dynamic> json) {
    return VixStatus(
      value: (json['value'] as num? ?? 0).toDouble(),
      change1d: (json['change_1d'] as num? ?? 0).toDouble(),
      level: json['level'] as String? ?? 'neutral',
    );
  }
}

class FearGreedIndex {
  final int score; // 0-100
  final String label;
  final String description;

  const FearGreedIndex({
    required this.score,
    required this.label,
    required this.description,
  });

  factory FearGreedIndex.fromJson(Map<String, dynamic> json) {
    return FearGreedIndex(
      score: (json['score'] as num? ?? 50).toInt(),
      label: json['label'] as String? ?? 'Neutral',
      description: json['description'] as String? ?? '',
    );
  }
}

class FedRate {
  final double value;
  final String targetRange;
  final String? lastChange;

  const FedRate({
    required this.value,
    required this.targetRange,
    this.lastChange,
  });

  factory FedRate.fromJson(Map<String, dynamic> json) {
    return FedRate(
      value: (json['value'] as num? ?? 0).toDouble(),
      targetRange: json['target_range'] as String? ?? 'N/A',
      lastChange: json['last_change'] as String?,
    );
  }
}

class CpiData {
  final double value;
  final double? previous;
  final double? change;
  final String? releaseDate;

  const CpiData({
    required this.value,
    this.previous,
    this.change,
    this.releaseDate,
  });

  factory CpiData.fromJson(Map<String, dynamic> json) {
    return CpiData(
      value: (json['value'] as num? ?? 0).toDouble(),
      previous: (json['previous'] as num?)?.toDouble(),
      change: (json['change'] as num?)?.toDouble(),
      releaseDate: json['release_date'] as String?,
    );
  }
}

class UnemploymentData {
  final double value;
  final double? previous;
  final double? change;

  const UnemploymentData({
    required this.value,
    this.previous,
    this.change,
  });

  factory UnemploymentData.fromJson(Map<String, dynamic> json) {
    return UnemploymentData(
      value: (json['value'] as num? ?? 0).toDouble(),
      previous: (json['previous'] as num?)?.toDouble(),
      change: (json['change'] as num?)?.toDouble(),
    );
  }
}

class TreasurySpread {
  final double value;
  /// "normal", "flattening", "inverted"
  final String signal;

  const TreasurySpread({required this.value, required this.signal});

  factory TreasurySpread.fromJson(Map<String, dynamic> json) {
    return TreasurySpread(
      value: (json['value'] as num? ?? 0).toDouble(),
      signal: json['signal'] as String? ?? 'normal',
    );
  }
}

class RegimeInfo {
  final String current;
  final double confidence;

  const RegimeInfo({required this.current, required this.confidence});

  factory RegimeInfo.fromJson(Map<String, dynamic> json) {
    return RegimeInfo(
      current: json['current'] as String? ?? 'unknown',
      confidence: (json['confidence'] as num? ?? 0).toDouble(),
    );
  }
}

class FredHistoryData {
  final String seriesId;
  final String name;
  final String frequency;
  final List<FredDataPoint> data;

  const FredHistoryData({
    required this.seriesId,
    required this.name,
    required this.frequency,
    required this.data,
  });

  factory FredHistoryData.fromJson(Map<String, dynamic> json) {
    final rawData = json['data'] as List? ?? [];
    return FredHistoryData(
      seriesId: json['series_id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      frequency: json['frequency'] as String? ?? '',
      data: rawData
          .map((e) => FredDataPoint.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

class FredDataPoint {
  final DateTime date;
  final double value;

  const FredDataPoint({required this.date, required this.value});

  factory FredDataPoint.fromJson(Map<String, dynamic> json) {
    return FredDataPoint(
      date: json['date'] != null
          ? DateTime.tryParse(json['date'].toString()) ?? DateTime.now()
          : DateTime.now(),
      value: (json['value'] as num? ?? 0).toDouble(),
    );
  }
}

class EconomicEvent {
  final String date;
  final String? time;
  final String event;
  /// "high", "medium", "low"
  final String impact;
  final String? previous;
  final String? forecast;
  final String? actual;

  const EconomicEvent({
    required this.date,
    this.time,
    required this.event,
    required this.impact,
    this.previous,
    this.forecast,
    this.actual,
  });

  factory EconomicEvent.fromJson(Map<String, dynamic> json) {
    return EconomicEvent(
      date: json['date'] as String? ?? '',
      time: json['time'] as String?,
      event: json['event'] as String? ?? '',
      impact: json['impact'] as String? ?? 'low',
      previous: json['previous'] as String?,
      forecast: json['forecast'] as String?,
      actual: json['actual'] as String?,
    );
  }
}

class RateOutlook {
  final double currentRate;
  final String? nextMeeting;
  /// e.g. {"cut_25bp": 35, "hold": 55, "hike_25bp": 10}
  final Map<String, int> probabilities;
  final double? yearEndEstimate;
  final String source;

  const RateOutlook({
    required this.currentRate,
    this.nextMeeting,
    required this.probabilities,
    this.yearEndEstimate,
    required this.source,
  });

  factory RateOutlook.fromJson(Map<String, dynamic> json) {
    final rawProbs = json['probabilities'] as Map<String, dynamic>? ?? {};
    return RateOutlook(
      currentRate: (json['current_rate'] as num? ?? 0).toDouble(),
      nextMeeting: json['next_meeting'] as String?,
      probabilities: rawProbs
          .map((k, v) => MapEntry(k, (v as num? ?? 0).toInt())),
      yearEndEstimate: (json['year_end_estimate'] as num?)?.toDouble(),
      source: json['source'] as String? ?? '',
    );
  }
}

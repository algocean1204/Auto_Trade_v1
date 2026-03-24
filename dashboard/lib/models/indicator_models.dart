// 인디케이터 관련 데이터 모델이다.

class IndicatorWeights {
  final Map<String, double> weights;
  final List<WeightPreset> presets;

  IndicatorWeights({
    required this.weights,
    required this.presets,
  });

  factory IndicatorWeights.fromJson(Map<String, dynamic> json) {
    final rawWeights = json['weights'] as Map<String, dynamic>? ?? {};
    final weightsMap = rawWeights
        .map((key, value) => MapEntry(key, (value as num? ?? 0).toDouble()));

    // 백엔드가 presets를 List<String> (이름만) 또는 List<Map> (name+weights) 형식으로 반환할 수 있다
    List<WeightPreset> presetsList = [];
    final rawPresets = json['presets'];
    if (rawPresets is List) {
      for (final preset in rawPresets) {
        if (preset is Map<String, dynamic>) {
          // 전체 객체 형식
          try {
            presetsList.add(WeightPreset.fromJson(preset));
          } catch (_) {
            // 이름만 있는 경우 빈 가중치로 생성
            if (preset['name'] != null) {
              presetsList.add(WeightPreset(
                name: preset['name'] as String,
                weights: {},
              ));
            }
          }
        } else if (preset is String) {
          // 이름만 있는 경우
          presetsList.add(WeightPreset(name: preset, weights: {}));
        }
      }
    }

    return IndicatorWeights(
      weights: weightsMap,
      presets: presetsList,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'weights': weights,
    };
  }
}

class WeightPreset {
  final String name;
  final Map<String, double> weights;

  WeightPreset({
    required this.name,
    required this.weights,
  });

  factory WeightPreset.fromJson(Map<String, dynamic> json) {
    Map<String, double> weightsMap = {};
    if (json['weights'] != null) {
      weightsMap = (json['weights'] as Map<String, dynamic>)
          .map((key, value) => MapEntry(key, (value as num? ?? 0).toDouble()));
    }

    return WeightPreset(
      name: json['name'] as String? ?? '',
      weights: weightsMap,
    );
  }
}

class RealtimeIndicator {
  final String ticker;
  final Map<String, dynamic> indicators;
  final List<IndicatorHistory>? history;
  final DateTime updatedAt;

  RealtimeIndicator({
    required this.ticker,
    required this.indicators,
    this.history,
    required this.updatedAt,
  });

  /// 백엔드 RealtimeIndicatorResponse는 flat 구조이다:
  /// {ticker, rsi, macd: {value, signal, histogram}, bollinger: {upper, lower, middle}, atr, volume, timestamp}
  /// indicators 래핑 키가 있으면 사용하고, 없으면 json 자체를 indicators로 매핑한다.
  factory RealtimeIndicator.fromJson(Map<String, dynamic> json) {
    List<IndicatorHistory>? historyList;
    if (json['history'] != null) {
      historyList = (json['history'] as List)
          .map((h) => IndicatorHistory.fromJson(h as Map<String, dynamic>))
          .toList();
    }

    // 백엔드 flat 구조 대응: indicators 키가 없으면 json 자체에서 지표 값을 추출한다
    final Map<String, dynamic> indicatorData;
    if (json['indicators'] is Map<String, dynamic>) {
      indicatorData = json['indicators'] as Map<String, dynamic>;
    } else {
      // flat 구조에서 지표 관련 필드를 추출한다
      indicatorData = <String, dynamic>{};
      if (json['rsi'] != null) indicatorData['rsi'] = json['rsi'];
      if (json['macd'] != null) indicatorData['macd'] = json['macd'];
      if (json['bollinger'] != null) {
        indicatorData['bollinger'] = json['bollinger'];
      }
      if (json['atr'] != null) indicatorData['atr'] = json['atr'];
      if (json['volume'] != null) indicatorData['volume'] = json['volume'];
    }

    // timestamp -> updated_at fallback 처리
    final String? timeStr =
        json['updated_at'] as String? ?? json['timestamp'] as String?;

    return RealtimeIndicator(
      ticker: json['ticker'] as String? ?? '',
      indicators: indicatorData,
      history: historyList,
      updatedAt: timeStr != null
          ? (DateTime.tryParse(timeStr) ?? DateTime.now())
          : DateTime.now(),
    );
  }
}

class IndicatorHistory {
  final DateTime timestamp;
  final double value;

  IndicatorHistory({
    required this.timestamp,
    required this.value,
  });

  factory IndicatorHistory.fromJson(Map<String, dynamic> json) {
    return IndicatorHistory(
      timestamp: json['timestamp'] != null
          ? (DateTime.tryParse(json['timestamp'] as String) ?? DateTime.now())
          : DateTime.now(),
      value: (json['value'] as num? ?? 0).toDouble(),
    );
  }
}

enum IndicatorCategory {
  momentum,
  trend,
  volatility,
}

class IndicatorInfo {
  final String id;
  final String displayName;
  final IndicatorCategory category;
  final String description;
  // 로컬라이제이션 키이다. AppStrings.get(descKey, locale)으로 설명을 가져온다.
  final String descKey;

  IndicatorInfo({
    required this.id,
    required this.displayName,
    required this.category,
    required this.description,
    required this.descKey,
  });

  /// locale에 맞는 설명을 반환한다. AppStrings를 직접 import하지 않도록
  /// 외부에서 AppStrings.get(info.descKey, locale)을 사용한다.

  static final List<IndicatorInfo> all = [
    IndicatorInfo(
      id: 'rsi_14',
      displayName: 'RSI (14)',
      category: IndicatorCategory.momentum,
      description: '상대강도지수 - 과매수/과매도 판단',
      descKey: 'rsi_desc',
    ),
    IndicatorInfo(
      id: 'macd',
      displayName: 'MACD',
      category: IndicatorCategory.momentum,
      description: '이동평균 수렴확산 - 추세 전환 신호',
      descKey: 'macd_desc',
    ),
    IndicatorInfo(
      id: 'stochastic',
      displayName: 'Stochastic',
      category: IndicatorCategory.momentum,
      description: '스토캐스틱 오실레이터 - 모멘텀 지표',
      descKey: 'stochastic_desc',
    ),
    IndicatorInfo(
      id: 'ma_cross',
      displayName: 'MA Cross',
      category: IndicatorCategory.trend,
      description: '이동평균선 교차 - 골든/데드 크로스',
      descKey: 'ma_cross_desc',
    ),
    IndicatorInfo(
      id: 'adx',
      displayName: 'ADX',
      category: IndicatorCategory.trend,
      description: '평균방향지수 - 추세 강도 측정',
      descKey: 'adx_desc',
    ),
    IndicatorInfo(
      id: 'bollinger',
      displayName: 'Bollinger Bands',
      category: IndicatorCategory.volatility,
      description: '볼린저 밴드 - 변동성 기반 매매',
      descKey: 'bollinger_desc',
    ),
    IndicatorInfo(
      id: 'atr',
      displayName: 'ATR',
      category: IndicatorCategory.volatility,
      description: '평균 실제 범위 - 변동성 측정',
      descKey: 'atr_desc',
    ),
  ];

  static IndicatorInfo? findById(String id) {
    try {
      return all.firstWhere((info) => info.id == id);
    } catch (e) {
      return null;
    }
  }
}

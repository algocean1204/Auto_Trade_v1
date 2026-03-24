// RSI 트리플 지표 데이터 모델이다.

class RsiIndicator {
  final double rsi;
  final double signal;
  final double histogram;
  final List<double> rsiSeries;
  final List<double> signalSeries;
  final bool overbought;
  final bool oversold;

  RsiIndicator({
    required this.rsi,
    required this.signal,
    required this.histogram,
    required this.rsiSeries,
    required this.signalSeries,
    required this.overbought,
    required this.oversold,
  });

  factory RsiIndicator.fromJson(Map<String, dynamic> json) {
    return RsiIndicator(
      rsi: (json['rsi'] as num? ?? 50).toDouble(),
      signal: (json['signal'] as num? ?? 50).toDouble(),
      histogram: (json['histogram'] as num? ?? 0).toDouble(),
      rsiSeries: (json['rsi_series'] as List?)
              ?.map((e) => (e as num).toDouble())
              .toList() ??
          [],
      signalSeries: (json['signal_series'] as List?)
              ?.map((e) => (e as num).toDouble())
              .toList() ??
          [],
      overbought: json['overbought'] as bool? ?? false,
      oversold: json['oversold'] as bool? ?? false,
    );
  }

  String get status {
    if (overbought) return 'overbought';
    if (oversold) return 'oversold';
    return 'neutral';
  }
}

class TripleRsiData {
  final RsiIndicator rsi7;
  final RsiIndicator rsi14;
  final RsiIndicator rsi21;
  final String consensus; // "bullish", "bearish", "neutral"
  final bool divergence;
  final List<String> dates;
  final String ticker;
  final String analysisTicker; // underlying

  TripleRsiData({
    required this.rsi7,
    required this.rsi14,
    required this.rsi21,
    required this.consensus,
    required this.divergence,
    required this.dates,
    required this.ticker,
    required this.analysisTicker,
  });

  factory TripleRsiData.fromJson(Map<String, dynamic> json) {
    return TripleRsiData(
      rsi7: RsiIndicator.fromJson(
          (json['rsi_7'] as Map<String, dynamic>?) ?? {}),
      rsi14: RsiIndicator.fromJson(
          (json['rsi_14'] as Map<String, dynamic>?) ?? {}),
      rsi21: RsiIndicator.fromJson(
          (json['rsi_21'] as Map<String, dynamic>?) ?? {}),
      consensus: json['consensus'] as String? ?? 'neutral',
      divergence: json['divergence'] as bool? ?? false,
      dates: (json['dates'] as List?)?.cast<String>() ?? [],
      ticker: json['ticker'] as String? ?? '',
      analysisTicker: json['analysis_ticker'] as String? ?? '',
    );
  }

  /// 주어진 RSI 종류에 맞는 시리즈를 반환한다.
  RsiIndicator indicatorFor(int period) {
    switch (period) {
      case 7:
        return rsi7;
      case 14:
        return rsi14;
      case 21:
        return rsi21;
      default:
        return rsi14;
    }
  }
}

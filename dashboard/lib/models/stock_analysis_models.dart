import 'package:flutter/material.dart';
import '../theme/domain_colors.dart';

/// 가격 히스토리 포인트 모델이다.
class PricePoint {
  final String date;
  final double close;
  final int volume;

  const PricePoint({
    required this.date,
    required this.close,
    required this.volume,
  });

  factory PricePoint.fromJson(Map<String, dynamic> json) {
    return PricePoint(
      date: json['date'] as String? ?? '',
      close: (json['close'] as num? ?? 0).toDouble(),
      volume: (json['volume'] as num? ?? 0).toInt(),
    );
  }
}

/// 기술적 지표 요약 모델이다.
class TechnicalSummary {
  final double compositeScore;
  final double rsi14;
  final String macdSignal;
  final String trend;
  final double support;
  final double resistance;

  const TechnicalSummary({
    required this.compositeScore,
    required this.rsi14,
    required this.macdSignal,
    required this.trend,
    required this.support,
    required this.resistance,
  });

  factory TechnicalSummary.fromJson(Map<String, dynamic> json) {
    return TechnicalSummary(
      compositeScore: (json['composite_score'] as num? ?? 0).toDouble(),
      rsi14: (json['rsi_14'] as num? ?? 50).toDouble(),
      macdSignal: json['macd_signal'] as String? ?? 'neutral',
      trend: json['trend'] as String? ?? 'sideways',
      support: (json['support'] as num? ?? 0).toDouble(),
      resistance: (json['resistance'] as num? ?? 0).toDouble(),
    );
  }

  /// compositeScore에 따른 색상을 반환한다.
  Color get scoreColor {
    if (compositeScore > 0.3) return DomainColors.scorePositive;
    if (compositeScore < -0.3) return DomainColors.scoreNegative;
    return DomainColors.scoreNeutral;
  }

  /// RSI 값에 따른 색상을 반환한다.
  Color get rsiColor {
    if (rsi14 > 70) return DomainColors.rsiOverbought;
    if (rsi14 < 30) return DomainColors.rsiOversold;
    return DomainColors.rsiNeutral;
  }

  /// RSI 상태 레이블을 반환한다.
  String get rsiLabel {
    if (rsi14 > 70) return '과매수';
    if (rsi14 < 30) return '과매도';
    return '중립';
  }

  /// MACD 신호 색상을 반환한다.
  Color get macdColor {
    switch (macdSignal.toLowerCase()) {
      case 'bullish':
        return DomainColors.bullish;
      case 'bearish':
        return DomainColors.bearish;
      default:
        return DomainColors.neutral;
    }
  }

  /// 추세 색상을 반환한다.
  Color get trendColor {
    switch (trend.toLowerCase()) {
      case 'uptrend':
      case 'up':
        return DomainColors.bullish;
      case 'downtrend':
      case 'down':
        return DomainColors.bearish;
      default:
        return DomainColors.neutral;
    }
  }
}

/// 기간별 예측 모델이다.
class Prediction {
  final String timeframe;
  final String direction;
  final int confidence;
  final double targetPrice;
  final String reasoning;

  const Prediction({
    required this.timeframe,
    required this.direction,
    required this.confidence,
    required this.targetPrice,
    required this.reasoning,
  });

  factory Prediction.fromJson(Map<String, dynamic> json) {
    return Prediction(
      timeframe: json['timeframe'] as String? ?? '',
      direction: json['direction'] as String? ?? 'neutral',
      confidence: (json['confidence'] as num? ?? 50).toInt(),
      targetPrice: (json['target_price'] as num? ?? 0).toDouble(),
      reasoning: json['reasoning'] as String? ?? '',
    );
  }

  /// direction에 따른 색상을 반환한다.
  Color get directionColor {
    switch (direction.toLowerCase()) {
      case 'bullish':
        return DomainColors.bullish;
      case 'bearish':
        return DomainColors.bearish;
      default:
        return DomainColors.neutral;
    }
  }

  /// direction 화살표 아이콘을 반환한다.
  IconData get directionIcon {
    switch (direction.toLowerCase()) {
      case 'bullish':
        return Icons.trending_up_rounded;
      case 'bearish':
        return Icons.trending_down_rounded;
      default:
        return Icons.trending_flat_rounded;
    }
  }

  /// direction 레이블을 반환한다.
  String get directionLabel {
    switch (direction.toLowerCase()) {
      case 'bullish':
        return '상승';
      case 'bearish':
        return '하락';
      default:
        return '중립';
    }
  }
}

/// 매매 추천 모델이다.
class Recommendation {
  final String action;
  final String reasoning;

  const Recommendation({
    required this.action,
    required this.reasoning,
  });

  factory Recommendation.fromJson(Map<String, dynamic> json) {
    return Recommendation(
      action: json['action'] as String? ?? 'hold',
      reasoning: json['reasoning'] as String? ?? '',
    );
  }

  /// action에 따른 색상을 반환한다.
  Color get actionColor {
    switch (action.toLowerCase()) {
      case 'buy':
        return DomainColors.signalBuy;
      case 'sell':
        return DomainColors.signalSell;
      default:
        return DomainColors.signalHold;
    }
  }

  /// action 한국어 레이블을 반환한다.
  String get actionLabel {
    switch (action.toLowerCase()) {
      case 'buy':
        return '매수';
      case 'sell':
        return '매도';
      default:
        return '보유';
    }
  }
}

/// AI 분석 결과 모델이다.
class AiAnalysis {
  final String currentSituation;
  final String reasoning;
  final List<String> keyFactors;
  final List<String> riskFactors;
  final List<Prediction> predictions;
  final Recommendation recommendation;

  const AiAnalysis({
    required this.currentSituation,
    required this.reasoning,
    required this.keyFactors,
    required this.riskFactors,
    required this.predictions,
    required this.recommendation,
  });

  factory AiAnalysis.fromJson(Map<String, dynamic> json) {
    final rawKeyFactors = json['key_factors'];
    final List<String> keyFactors = rawKeyFactors is List
        ? rawKeyFactors.map((e) => e.toString()).toList()
        : [];

    final rawRiskFactors = json['risk_factors'];
    final List<String> riskFactors = rawRiskFactors is List
        ? rawRiskFactors.map((e) => e.toString()).toList()
        : [];

    final rawPredictions = json['predictions'];
    final List<Prediction> predictions = rawPredictions is List
        ? rawPredictions
            .map((e) => Prediction.fromJson(e as Map<String, dynamic>))
            .toList()
        : [];

    final rawRecommendation = json['recommendation'];
    final Recommendation recommendation = rawRecommendation is Map
        ? Recommendation.fromJson(rawRecommendation as Map<String, dynamic>)
        : const Recommendation(action: 'hold', reasoning: '');

    return AiAnalysis(
      currentSituation: json['current_situation'] as String? ?? '',
      reasoning: json['reasoning'] as String? ?? '',
      keyFactors: keyFactors,
      riskFactors: riskFactors,
      predictions: predictions,
      recommendation: recommendation,
    );
  }
}

/// 관련 뉴스 모델이다.
class AnalysisNews {
  final String id;
  final String headline;
  final String? headlineOriginal;
  final String? summaryKo;
  final Map<String, String>? companiesImpact;
  final String? publishedAt;
  final double? sentimentScore;
  final String impact;
  final String source;

  const AnalysisNews({
    required this.id,
    required this.headline,
    this.headlineOriginal,
    this.summaryKo,
    this.companiesImpact,
    this.publishedAt,
    this.sentimentScore,
    required this.impact,
    required this.source,
  });

  factory AnalysisNews.fromJson(Map<String, dynamic> json) {
    // companies_impact 파싱한다.
    final rawCompaniesImpact = json['companies_impact'];
    Map<String, String>? companiesImpact;
    if (rawCompaniesImpact is Map && rawCompaniesImpact.isNotEmpty) {
      companiesImpact = rawCompaniesImpact.map(
        (k, v) => MapEntry(k.toString(), v?.toString() ?? ''),
      );
    }

    // 한국어 헤드라인 우선 선택한다.
    final headlineKr = json['headline_kr'] as String?;
    final headline = json['headline'] as String? ?? '';
    final displayHeadline =
        (headlineKr != null && headlineKr.isNotEmpty) ? headlineKr : headline;

    return AnalysisNews(
      id: json['id'] as String? ?? '',
      headline: displayHeadline,
      headlineOriginal: headline,
      summaryKo: json['summary_ko'] as String?,
      companiesImpact: companiesImpact,
      publishedAt: json['published_at'] as String?,
      sentimentScore: (json['sentiment_score'] as num?)?.toDouble(),
      impact: json['impact'] as String? ?? 'low',
      source: json['source'] as String? ?? '',
    );
  }

  /// impact에 따른 색상을 반환한다.
  Color get impactColor {
    switch (impact.toLowerCase()) {
      case 'high':
        return DomainColors.analysisImpactHigh;
      case 'medium':
        return DomainColors.analysisImpactMedium;
      default:
        return DomainColors.analysisImpactLow;
    }
  }

  /// impact 한국어 레이블을 반환한다.
  String get impactLabel {
    switch (impact.toLowerCase()) {
      case 'high':
        return '높음';
      case 'medium':
        return '보통';
      default:
        return '낮음';
    }
  }

  /// 발행 날짜 문자열을 파싱하여 날짜 키를 반환한다 (YYYY-MM-DD 형식).
  String get dateKey {
    final pa = publishedAt;
    if (pa == null || pa.isEmpty) return '';
    try {
      final dt = DateTime.parse(pa);
      return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';
    } catch (_) {
      return pa.length >= 10 ? pa.substring(0, 10) : pa;
    }
  }

  /// 발행 시간 문자열을 반환한다 (HH:MM 형식).
  String get timeLabel {
    final pa = publishedAt;
    if (pa == null || pa.isEmpty) return '';
    try {
      final dt = DateTime.parse(pa).toLocal();
      return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {
      return '';
    }
  }

  /// source 이름을 가독성 좋게 변환한다.
  String get sourceLabel {
    final lower = source.toLowerCase();
    if (lower.contains('reuters')) return 'Reuters';
    if (lower.contains('bloomberg')) return 'Bloomberg';
    if (lower.contains('cnbc')) return 'CNBC';
    if (lower.contains('wsj') || lower.contains('wall_street')) return 'WSJ';
    if (lower.contains('ft') || lower.contains('financial_times')) return 'FT';
    if (lower.contains('marketwatch')) return 'MarketWatch';
    if (lower.contains('seeking_alpha') || lower.contains('seekingalpha')) {
      return 'SeekingAlpha';
    }
    if (lower.contains('yahoo')) return 'Yahoo Finance';
    return source
        .replaceAll('_', ' ')
        .split(' ')
        .map((w) => w.isEmpty ? '' : '${w[0].toUpperCase()}${w.substring(1)}')
        .join(' ');
  }
}

/// 종합 종목 분석 데이터 모델이다.
class StockAnalysisData {
  final String ticker;
  final double currentPrice;
  final double priceChangePct;
  final String analysisTimestamp;
  final TechnicalSummary technicalSummary;
  final AiAnalysis aiAnalysis;

  /// AI 분석이 성공적으로 수행되었는지 여부이다.
  /// false이면 기술적 지표 데이터만 유효하다.
  final bool aiAvailable;
  final List<AnalysisNews> relatedNews;
  final List<PricePoint> priceHistory;

  const StockAnalysisData({
    required this.ticker,
    required this.currentPrice,
    required this.priceChangePct,
    required this.analysisTimestamp,
    required this.technicalSummary,
    required this.aiAnalysis,
    this.aiAvailable = false,
    required this.relatedNews,
    required this.priceHistory,
  });

  factory StockAnalysisData.fromJson(Map<String, dynamic> json) {
    final rawTechnical = json['technical_summary'];
    final TechnicalSummary technicalSummary = rawTechnical is Map
        ? TechnicalSummary.fromJson(rawTechnical as Map<String, dynamic>)
        : TechnicalSummary(
            compositeScore: 0,
            rsi14: 50,
            macdSignal: 'neutral',
            trend: 'sideways',
            support: 0,
            resistance: 0,
          );

    final rawAi = json['ai_analysis'];
    final AiAnalysis aiAnalysis = rawAi is Map
        ? AiAnalysis.fromJson(rawAi as Map<String, dynamic>)
        : AiAnalysis(
            currentSituation: '',
            reasoning: '',
            keyFactors: [],
            riskFactors: [],
            predictions: [],
            recommendation: const Recommendation(action: 'hold', reasoning: ''),
          );

    final rawNews = json['related_news'];
    final List<AnalysisNews> relatedNews = rawNews is List
        ? rawNews
            .map((e) => AnalysisNews.fromJson(e as Map<String, dynamic>))
            .toList()
        : [];

    final rawHistory = json['price_history'];
    final List<PricePoint> priceHistory = rawHistory is List
        ? rawHistory
            .map((e) => PricePoint.fromJson(e as Map<String, dynamic>))
            .toList()
        : [];

    return StockAnalysisData(
      ticker: json['ticker'] as String? ?? '',
      currentPrice: (json['current_price'] as num? ?? 0).toDouble(),
      priceChangePct: (json['price_change_pct'] as num? ?? 0).toDouble(),
      analysisTimestamp: json['analysis_timestamp'] as String? ?? '',
      technicalSummary: technicalSummary,
      aiAnalysis: aiAnalysis,
      aiAvailable: json['ai_available'] as bool? ?? false,
      relatedNews: relatedNews,
      priceHistory: priceHistory,
    );
  }

  /// priceChangePct 색상을 반환한다.
  Color get priceChangeColor =>
      priceChangePct >= 0 ? DomainColors.priceUp : DomainColors.priceDown;

  /// priceChangePct 부호 포함 문자열을 반환한다.
  String get priceChangeLabel {
    final sign = priceChangePct >= 0 ? '+' : '';
    return '$sign${priceChangePct.toStringAsFixed(2)}%';
  }
}

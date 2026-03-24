import 'package:flutter/material.dart';
import '../theme/domain_colors.dart';

/// 매매 근거 날짜 및 거래 수 모델이다.
class TradeReasoningDate {
  final String date;
  final int count;

  const TradeReasoningDate({
    required this.date,
    required this.count,
  });

  factory TradeReasoningDate.fromJson(Map<String, dynamic> json) {
    return TradeReasoningDate(
      date: json['date'] as String? ?? '',
      // 백엔드는 'trade_count' 키로 반환한다
      count: (json['trade_count'] as num?)?.toInt() ??
          (json['count'] as num? ?? 0).toInt(),
    );
  }
}

/// AI 분석 근거 세부 정보 모델이다.
class TradeReasoningDetail {
  final String summary;
  final String? indicatorDirection;
  final double? indicatorConfidence;
  final List<dynamic> signals;

  const TradeReasoningDetail({
    required this.summary,
    this.indicatorDirection,
    this.indicatorConfidence,
    required this.signals,
  });

  factory TradeReasoningDetail.fromJson(Map<String, dynamic> json) {
    final rawSignals = json['signals'];
    final List<dynamic> signalsList;
    if (rawSignals is List) {
      signalsList = rawSignals;
    } else {
      signalsList = [];
    }

    return TradeReasoningDetail(
      summary: json['summary'] as String? ?? '',
      indicatorDirection: json['indicator_direction'] as String?,
      indicatorConfidence:
          (json['indicator_confidence'] as num?)?.toDouble(),
      signals: signalsList,
    );
  }
}

/// 매매 근거 전체 모델이다.
class TradeReasoning {
  final String id;
  final String ticker;
  final String direction; // long / short
  final String action;    // buy / sell
  final double entryPrice;
  final double? exitPrice;
  final DateTime entryAt;
  final DateTime? exitAt;
  final double? pnlPct;
  final double? pnlAmount;
  final int? holdMinutes;
  final String status; // open / closed
  final double? aiConfidence;
  final String? marketRegime;
  final TradeReasoningDetail reasoning;
  final String? exitReason;
  final Map<String, dynamic>? postAnalysis;

  const TradeReasoning({
    required this.id,
    required this.ticker,
    required this.direction,
    required this.action,
    required this.entryPrice,
    this.exitPrice,
    required this.entryAt,
    this.exitAt,
    this.pnlPct,
    this.pnlAmount,
    this.holdMinutes,
    required this.status,
    this.aiConfidence,
    this.marketRegime,
    required this.reasoning,
    this.exitReason,
    this.postAnalysis,
  });

  factory TradeReasoning.fromJson(Map<String, dynamic> json) {
    DateTime entryAt;
    try {
      entryAt = DateTime.parse(json['entry_at'] as String? ?? '');
    } catch (_) {
      entryAt = DateTime.now();
    }

    DateTime? exitAt;
    final rawExitAt = json['exit_at'];
    if (rawExitAt is String && rawExitAt.isNotEmpty) {
      try {
        exitAt = DateTime.parse(rawExitAt);
      } catch (_) {
        exitAt = null;
      }
    }

    final rawReasoning = json['reasoning'];
    final TradeReasoningDetail reasoningDetail;
    if (rawReasoning is Map<String, dynamic>) {
      reasoningDetail = TradeReasoningDetail.fromJson(rawReasoning);
    } else {
      reasoningDetail = const TradeReasoningDetail(
        summary: '',
        signals: [],
      );
    }

    final rawPostAnalysis = json['post_analysis'];
    final Map<String, dynamic>? postAnalysis;
    if (rawPostAnalysis is Map<String, dynamic>) {
      postAnalysis = rawPostAnalysis;
    } else {
      postAnalysis = null;
    }

    return TradeReasoning(
      id: json['id'] as String? ?? '',
      ticker: json['ticker'] as String? ?? '',
      direction: json['direction'] as String? ?? 'long',
      action: json['action'] as String? ?? 'buy',
      entryPrice: (json['entry_price'] as num? ?? 0).toDouble(),
      exitPrice: (json['exit_price'] as num?)?.toDouble(),
      entryAt: entryAt,
      exitAt: exitAt,
      pnlPct: (json['pnl_pct'] as num?)?.toDouble(),
      pnlAmount: (json['pnl_amount'] as num?)?.toDouble(),
      holdMinutes: (json['hold_minutes'] as num?)?.toInt(),
      status: json['status'] as String? ?? 'open',
      aiConfidence: (json['ai_confidence'] as num?)?.toDouble(),
      marketRegime: json['market_regime'] as String?,
      reasoning: reasoningDetail,
      exitReason: json['exit_reason'] as String?,
      postAnalysis: postAnalysis,
    );
  }

  /// 방향에 따른 주요 색상을 반환한다.
  Color get directionColor {
    switch (direction.toLowerCase()) {
      case 'long':
        return DomainColors.bullish;
      case 'short':
        return DomainColors.bearish;
      default:
        return DomainColors.neutral;
    }
  }

  /// 거래 방향 아이콘을 반환한다.
  IconData get directionIcon {
    switch (direction.toLowerCase()) {
      case 'long':
        return Icons.trending_up_rounded;
      case 'short':
        return Icons.trending_down_rounded;
      default:
        return Icons.remove_rounded;
    }
  }

  /// 손익에 따른 카드 왼쪽 테두리 색상을 반환한다.
  Color get cardBorderColor {
    if (status == 'open') return DomainColors.statusOpen;
    if (pnlPct == null) return DomainColors.neutral;
    return (pnlPct ?? 0.0) >= 0 ? DomainColors.priceUp : DomainColors.priceDown;
  }

  /// AI 신뢰도에 따른 색상을 반환한다.
  Color confidenceColor(double confidence) {
    if (confidence >= 0.8) return DomainColors.scorePositive;
    if (confidence >= 0.6) return DomainColors.scoreNeutral;
    return DomainColors.scoreNegative;
  }

  /// 보유 시간을 포맷팅한다.
  String get holdDurationLabel {
    final minutes = holdMinutes;
    if (minutes == null) return '-';
    final h = minutes ~/ 60;
    final m = minutes % 60;
    if (h > 0) return '$h시간 $m분';
    return '$m분';
  }

  /// 피드백 데이터가 있는지 확인한다.
  /// 백엔드는 post_analysis["user_feedback"] 키에 저장한다.
  bool get hasFeedback {
    final analysis = postAnalysis;
    if (analysis == null) return false;
    return analysis['user_feedback'] != null;
  }

  /// 피드백 내용을 반환한다.
  String? get feedbackText {
    final analysis = postAnalysis;
    if (analysis == null) return null;
    final fb = analysis['user_feedback'];
    if (fb is Map) return fb['feedback'] as String?;
    return null;
  }

  /// 피드백 평점을 반환한다.
  int? get feedbackRating {
    final analysis = postAnalysis;
    if (analysis == null) return null;
    final fb = analysis['user_feedback'];
    if (fb is Map) return (fb['rating'] as num?)?.toInt();
    return null;
  }
}

/// 일일 매매 통계 요약 모델이다.
class TradeReasoningStats {
  final int totalTrades;
  final int winCount;
  final int lossCount;
  final double totalPnl;
  final double avgWinConfidence;
  final double avgLossConfidence;
  final String? mostCommonRegime;
  final List<String> mostTradedTickers;

  const TradeReasoningStats({
    required this.totalTrades,
    required this.winCount,
    required this.lossCount,
    required this.totalPnl,
    required this.avgWinConfidence,
    required this.avgLossConfidence,
    this.mostCommonRegime,
    required this.mostTradedTickers,
  });

  factory TradeReasoningStats.fromJson(Map<String, dynamic> json) {
    // 백엔드는 'top_tickers' 키로 반환한다
    final rawTickers = json['top_tickers'] ?? json['most_traded_tickers'];
    final List<String> tickersList;
    if (rawTickers is List) {
      tickersList = rawTickers.map((e) {
        if (e is Map) return (e['ticker'] ?? e.toString()) as String;
        return e.toString();
      }).toList();
    } else {
      tickersList = [];
    }

    return TradeReasoningStats(
      totalTrades: (json['total_trades'] as num? ?? 0).toInt(),
      winCount: (json['win_count'] as num? ?? 0).toInt(),
      lossCount: (json['loss_count'] as num? ?? 0).toInt(),
      // 백엔드는 'total_pnl_amount' 키로 반환한다
      totalPnl: (json['total_pnl_amount'] as num?)?.toDouble() ??
          (json['total_pnl'] as num? ?? 0).toDouble(),
      // 백엔드는 'avg_confidence_winners' / 'avg_confidence_losers' 키로 반환한다
      avgWinConfidence: (json['avg_confidence_winners'] as num?)?.toDouble() ??
          (json['avg_win_confidence'] as num? ?? 0).toDouble(),
      avgLossConfidence: (json['avg_confidence_losers'] as num?)?.toDouble() ??
          (json['avg_loss_confidence'] as num? ?? 0).toDouble(),
      mostCommonRegime: json['most_common_regime'] as String?,
      mostTradedTickers: tickersList,
    );
  }

  /// 승률을 반환한다 (0~1).
  double get winRate {
    if (totalTrades == 0) return 0.0;
    return winCount / totalTrades;
  }

  /// 승률 퍼센트 문자열을 반환한다.
  String get winRateLabel {
    return '${(winRate * 100).toStringAsFixed(1)}%';
  }
}

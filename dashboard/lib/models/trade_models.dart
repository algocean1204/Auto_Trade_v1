class Position {
  final String ticker;
  final int quantity;
  final double avgPrice;
  final double currentPrice;
  final double unrealizedPnl;
  final double unrealizedPnlPct;
  final int holdDays;
  final DateTime entryTime;
  final String strategy;

  Position({
    required this.ticker,
    required this.quantity,
    required this.avgPrice,
    required this.currentPrice,
    required this.unrealizedPnl,
    required this.unrealizedPnlPct,
    required this.holdDays,
    required this.entryTime,
    required this.strategy,
  });

  factory Position.fromJson(Map<String, dynamic> json) {
    return Position(
      ticker: json['ticker'] as String? ?? '',
      quantity: json['quantity'] as int? ?? 0,
      avgPrice: (json['avg_price'] as num? ?? 0).toDouble(),
      currentPrice: (json['current_price'] as num? ?? 0).toDouble(),
      unrealizedPnl: (json['unrealized_pnl'] as num? ?? 0).toDouble(),
      unrealizedPnlPct: (json['unrealized_pnl_pct'] as num? ?? 0).toDouble(),
      holdDays: json['hold_days'] as int? ?? 0,
      // 백엔드가 빈 문자열 ""이나 잘못된 형식을 보낼 수 있으므로 tryParse로 안전하게 처리한다
      entryTime: (json['entry_time'] != null &&
              (json['entry_time'] as String).isNotEmpty)
          ? (DateTime.tryParse(json['entry_time'] as String) ?? DateTime.now())
          : DateTime.now(),
      strategy: json['strategy'] as String? ?? '',
    );
  }

  double get positionValue => quantity * currentPrice;
  bool get isProfit => unrealizedPnl >= 0;
}

class Trade {
  final int id;
  final String ticker;
  final String action;
  final int quantity;
  final double price;
  final double pnl;
  final double pnlPct;
  final String reason;
  final DateTime timestamp;

  Trade({
    required this.id,
    required this.ticker,
    required this.action,
    required this.quantity,
    required this.price,
    required this.pnl,
    required this.pnlPct,
    required this.reason,
    required this.timestamp,
  });

  factory Trade.fromJson(Map<String, dynamic> json) {
    return Trade(
      id: json['id'] as int? ?? 0,
      ticker: json['ticker'] as String? ?? '',
      action: json['action'] as String? ?? '',
      quantity: json['quantity'] as int? ?? 0,
      price: (json['price'] as num? ?? 0).toDouble(),
      pnl: (json['pnl'] as num? ?? 0).toDouble(),
      pnlPct: (json['pnl_pct'] as num? ?? 0).toDouble(),
      reason: json['reason'] as String? ?? '',
      // 백엔드가 빈 문자열 ""이나 잘못된 형식을 보낼 수 있으므로 tryParse로 안전하게 처리한다
      timestamp: (json['timestamp'] != null &&
              (json['timestamp'] as String).isNotEmpty)
          ? (DateTime.tryParse(json['timestamp'] as String) ?? DateTime.now())
          : DateTime.now(),
    );
  }

  bool get isBuy => action.toLowerCase() == 'buy';
  bool get isSell => action.toLowerCase() == 'sell';
}

class StrategyParams {
  final Map<String, dynamic> params;
  final Map<String, dynamic> regimes;

  StrategyParams({
    required this.params,
    required this.regimes,
  });

  factory StrategyParams.fromJson(Map<String, dynamic> json) {
    return StrategyParams(
      params: json['params'] as Map<String, dynamic>? ?? {},
      regimes: json['regimes'] as Map<String, dynamic>? ?? {},
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'params': params,
    };
  }
}

class FeedbackReport {
  final String reportType;
  final String reportDate;
  // 백엔드 DB의 content 컬럼은 JSONB(dict)이므로 Map으로 수신한다.
  // String으로 반환되는 경우(레거시)도 허용한다.
  final dynamic content;
  final DateTime createdAt;

  FeedbackReport({
    required this.reportType,
    required this.reportDate,
    required this.content,
    required this.createdAt,
  });

  /// content를 사람이 읽기 좋은 형식의 문자열로 반환한다.
  /// 백엔드가 Map(JSONB)으로 보내는 경우 주요 항목을 추출하여 가독성 있게 구성한다.
  String get contentString {
    if (content is String) return content as String;
    if (content is Map) {
      try {
        final map = content as Map;
        final buffer = StringBuffer();

        // summary 섹션이 있으면 요약 정보를 표시한다.
        final summary = map['summary'];
        if (summary is Map) {
          buffer.writeln('[거래 요약]');
          final totalTrades = summary['total_trades'] ?? 0;
          final winRate = summary['win_rate'] ?? 0.0;
          final totalPnl = summary['total_pnl'] ?? 0.0;
          buffer.writeln('총 거래: $totalTrades건');
          buffer.writeln('승률: ${(winRate is num ? winRate.toStringAsFixed(1) : winRate)}%');
          buffer.writeln('총 손익: \$${(totalPnl is num ? totalPnl.toStringAsFixed(2) : totalPnl)}');
          buffer.writeln('');
        }

        // by_ticker 섹션
        final byTicker = map['by_ticker'];
        if (byTicker is Map && byTicker.isNotEmpty) {
          buffer.writeln('[종목별 실적]');
          byTicker.forEach((key, value) {
            if (value is Map) {
              final trades = value['trades'] ?? 0;
              final pnl = value['total_pnl'] ?? 0.0;
              buffer.writeln('$key: ${trades}건, \$${(pnl is num ? pnl.toStringAsFixed(2) : pnl)}');
            }
          });
          buffer.writeln('');
        }

        // risk_metrics 섹션
        final risk = map['risk_metrics'];
        if (risk is Map) {
          buffer.writeln('[리스크 지표]');
          final mdd = risk['max_drawdown_pct'] ?? 0.0;
          final sharpe = risk['sharpe_estimate'] ?? 0.0;
          buffer.writeln('최대 낙폭: ${(mdd is num ? mdd.toStringAsFixed(2) : mdd)}%');
          buffer.writeln('샤프 비율: ${(sharpe is num ? sharpe.toStringAsFixed(2) : sharpe)}');
          buffer.writeln('');
        }

        // indicator_feedback 섹션
        final feedback = map['indicator_feedback'];
        if (feedback is Map) {
          final rec = feedback['recommendation'];
          if (rec != null && rec.toString().isNotEmpty) {
            buffer.writeln('[지표 피드백]');
            buffer.writeln(rec.toString());
          }
        }

        final result = buffer.toString().trim();
        return result.isNotEmpty ? result : '데이터가 비어 있습니다.';
      } catch (_) {
        return content.toString();
      }
    }
    return content?.toString() ?? '';
  }

  /// 백엔드 FeedbackReportResponse 구조에 맞춘 파싱이다:
  /// {period, summary: {total_trades, win_count, ...}, trades: [...], adjustments: [...], message}
  /// 기존 Flutter 구조(report_type, report_date, content, created_at)와 호환되도록 매핑한다.
  factory FeedbackReport.fromJson(Map<String, dynamic> json) {
    // report_type: 백엔드 period 또는 기존 report_type
    final reportType =
        json['report_type'] as String? ?? json['period'] as String? ?? '';

    // report_date: 백엔드 period를 날짜 대용으로 사용하거나 기존 report_date
    final reportDate =
        json['report_date'] as String? ?? json['period'] as String? ?? json['date'] as String? ?? '';

    // content: 기존 content 키가 있으면 사용, 없으면 summary 객체를 content로 매핑한다
    // summary가 있으면 전체 json을 content로 전달하여 contentString getter가 활용할 수 있게 한다
    final rawContent = json['content'] ?? (json.containsKey('summary') ? json : null);

    // created_at: 백엔드 응답에 created_at이 없을 수 있으므로 timestamp 등 fallback 처리
    final createdAtStr =
        json['created_at'] as String? ?? json['timestamp'] as String?;

    return FeedbackReport(
      reportType: reportType,
      reportDate: reportDate,
      content: rawContent,
      createdAt: createdAtStr != null
          ? (DateTime.tryParse(createdAtStr) ?? DateTime.now())
          : DateTime.now(),
    );
  }
}

class PendingAdjustment {
  // 백엔드 DB의 id는 UUID String이다. int 형으로 저장하면 파싱 실패한다.
  final String id;
  final String paramName;
  final dynamic currentValue;
  final dynamic proposedValue;
  final double changePct;
  final String reason;
  final String status;
  final DateTime createdAt;

  PendingAdjustment({
    required this.id,
    required this.paramName,
    required this.currentValue,
    required this.proposedValue,
    required this.changePct,
    required this.reason,
    required this.status,
    required this.createdAt,
  });

  factory PendingAdjustment.fromJson(Map<String, dynamic> json) {
    return PendingAdjustment(
      // 백엔드는 UUID 문자열로 id를 반환한다.
      id: (json['id'] ?? '').toString(),
      paramName: json['param_name'] as String? ?? '',
      currentValue: json['current_value'],
      proposedValue: json['proposed_value'],
      changePct: (json['change_pct'] as num? ?? 0).toDouble(),
      reason: json['reason'] as String? ?? '',
      status: json['status'] as String? ?? '',
      createdAt: json['created_at'] != null
          ? (DateTime.tryParse(json['created_at'] as String) ?? DateTime.now())
          : DateTime.now(),
    );
  }
}

// 종목별 AI 최적화 전략 파라미터 모델이다.

/// 전체 종목 파라미터 요약 정보이다.
class TickerParamsSummary {
  final String ticker;
  final String sector;
  final String riskGrade; // LOW, MEDIUM, HIGH
  final double takeProfitPct;
  final double stopLossPct;
  final double trailingStopPct;
  final double minConfidence;
  final double maxPositionPct;
  final int maxHoldDays;
  final bool hasUserOverride;
  final int overrideCount;
  final String? aiUpdatedAt;

  TickerParamsSummary({
    required this.ticker,
    required this.sector,
    required this.riskGrade,
    required this.takeProfitPct,
    required this.stopLossPct,
    required this.trailingStopPct,
    required this.minConfidence,
    required this.maxPositionPct,
    required this.maxHoldDays,
    required this.hasUserOverride,
    this.overrideCount = 0,
    this.aiUpdatedAt,
  });

  factory TickerParamsSummary.fromJson(Map<String, dynamic> json) {
    return TickerParamsSummary(
      ticker: json['ticker'] as String? ?? '',
      sector: json['sector'] as String? ?? '',
      riskGrade: json['risk_grade'] as String? ?? 'MEDIUM',
      takeProfitPct: (json['take_profit_pct'] as num? ?? 0).toDouble(),
      stopLossPct: (json['stop_loss_pct'] as num? ?? 0).toDouble(),
      trailingStopPct: (json['trailing_stop_pct'] as num? ?? 0).toDouble(),
      minConfidence: (json['min_confidence'] as num? ?? 0).toDouble(),
      maxPositionPct: (json['max_position_pct'] as num? ?? 0).toDouble(),
      maxHoldDays: json['max_hold_days'] as int? ?? 0,
      hasUserOverride: json['has_user_override'] as bool? ?? false,
      overrideCount: json['override_count'] as int? ?? 0,
      aiUpdatedAt: json['ai_updated_at'] as String?,
    );
  }
}

/// 단일 종목 상세 파라미터 정보이다.
class TickerParamsDetail {
  final String ticker;
  final Map<String, dynamic> aiRecommended;
  final Map<String, dynamic> aiAnalysis; // RSI values, volatility 등
  final String aiReasoning; // AI 분석 근거 (한국어)
  final String? aiUpdatedAt;
  final Map<String, dynamic> userOverride;
  final String? userUpdatedAt;
  final Map<String, dynamic> effective; // 병합된 최종 적용 파라미터

  TickerParamsDetail({
    required this.ticker,
    required this.aiRecommended,
    required this.aiAnalysis,
    required this.aiReasoning,
    this.aiUpdatedAt,
    required this.userOverride,
    this.userUpdatedAt,
    required this.effective,
  });

  /// 백엔드 TickerParamsSingleResponse는 {"ticker": "SOXL", "params": {...}} flat 구조이다.
  /// ai_recommended 등 세부 키가 있으면 그대로 사용하고,
  /// 없으면 params 또는 json 자체를 effective/aiRecommended로 매핑한다.
  factory TickerParamsDetail.fromJson(Map<String, dynamic> json) {
    // 백엔드 flat 구조: params 딕셔너리가 실질적인 파라미터 데이터이다
    final params = json['params'] is Map
        ? Map<String, dynamic>.from(json['params'] as Map)
        : <String, dynamic>{};

    return TickerParamsDetail(
      ticker: json['ticker'] as String? ?? '',
      aiRecommended: json.containsKey('ai_recommended')
          ? Map<String, dynamic>.from(json['ai_recommended'] as Map? ?? {})
          : Map<String, dynamic>.from(params),
      aiAnalysis: json.containsKey('ai_analysis')
          ? Map<String, dynamic>.from(json['ai_analysis'] as Map? ?? {})
          : <String, dynamic>{},
      aiReasoning: json['ai_reasoning'] as String? ?? '',
      aiUpdatedAt: json['ai_updated_at'] as String?,
      userOverride: json.containsKey('user_override')
          ? Map<String, dynamic>.from(json['user_override'] as Map? ?? {})
          : <String, dynamic>{},
      userUpdatedAt: json['user_updated_at'] as String?,
      effective: json.containsKey('effective')
          ? Map<String, dynamic>.from(json['effective'] as Map? ?? {})
          : Map<String, dynamic>.from(params),
    );
  }
}

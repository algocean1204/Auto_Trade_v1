// 환율 관련 데이터 모델이다.
//
// /api/fx/status 응답 구조:
// {
//   "usd_krw_rate": float,
//   "change_pct": float,
//   "updated_at": ISO8601 string,
//   "source": string,
// }
//
// /api/fx/history 응답 구조:
// {
//   "entries": [
//     {"date": "YYYY-MM-DD HH:MM", "rate": float, "change_pct": float},
//     ...
//   ]
// }

class FxStatus {
  final double usdKrwRate;

  /// 전일 대비 변동률 (%)이다.
  final double dailyChangePct;

  /// 환율 조회 시각이다.
  final DateTime updatedAt;

  /// 데이터 출처이다 (예: 'KIS', 'cache', 'fallback').
  final String source;

  FxStatus({
    required this.usdKrwRate,
    required this.dailyChangePct,
    required this.updatedAt,
    this.source = '',
  });

  /// source가 '조회불가'이거나 환율이 0이면 true이다.
  bool get isUnavailable => source == '조회불가' || usdKrwRate <= 0;

  factory FxStatus.fromJson(Map<String, dynamic> json) {
    // 'updated_at', 'timestamp' 순으로 폴백 처리한다
    final rawTimestamp = json['updated_at'] ?? json['timestamp'];

    return FxStatus(
      usdKrwRate: (json['usd_krw_rate'] as num? ?? 0).toDouble(),
      // 'change_pct' (V2), 'daily_change_pct' (V1 호환) 순으로 처리한다
      dailyChangePct:
          (json['change_pct'] as num? ?? json['daily_change_pct'] as num? ?? 0)
              .toDouble(),
      updatedAt: rawTimestamp != null && rawTimestamp.toString().isNotEmpty
          ? (DateTime.tryParse(rawTimestamp as String) ?? DateTime.now())
          : DateTime.now(),
      source: json['source'] as String? ?? '',
    );
  }
}

class FxHistoryPoint {
  /// 환율 기록 시각이다.
  final DateTime date;
  final double rate;

  /// 전일 대비 변동률 (%)이다.
  final double changePct;

  FxHistoryPoint({
    required this.date,
    required this.rate,
    this.changePct = 0.0,
  });

  factory FxHistoryPoint.fromJson(Map<String, dynamic> json) {
    // 'date', 'timestamp' 순으로 폴백 처리한다
    final rawDate = json['date'] ?? json['timestamp'];

    return FxHistoryPoint(
      date: rawDate != null && rawDate.toString().isNotEmpty
          ? (DateTime.tryParse(rawDate as String) ?? DateTime.now())
          : DateTime.now(),
      rate: (json['rate'] as num? ?? 0).toDouble(),
      changePct: (json['change_pct'] as num? ?? 0).toDouble(),
    );
  }
}

// 유니버스 관리 관련 데이터 모델이다.


class UniverseTickerEx {
  final String ticker;
  final String name;
  final String direction; // "bull" or "bear"
  final double leverage;
  final String? underlying;
  final double? expenseRatio;
  final int? avgDailyVolume;
  final bool enabled;

  UniverseTickerEx({
    required this.ticker,
    required this.name,
    required this.direction,
    required this.leverage,
    this.underlying,
    this.expenseRatio,
    this.avgDailyVolume,
    required this.enabled,
  });

  factory UniverseTickerEx.fromJson(Map<String, dynamic> json) {
    return UniverseTickerEx(
      ticker: json['ticker'] as String? ?? '',
      name: json['name'] as String? ?? '',
      direction: json['direction'] as String? ?? 'bull',
      leverage: (json['leverage'] as num? ?? 2.0).toDouble(),
      underlying: json['underlying'] as String?,
      expenseRatio: json['expense_ratio'] != null
          ? (json['expense_ratio'] as num).toDouble()
          : null,
      avgDailyVolume: json['avg_daily_volume'] as int?,
      enabled: json['enabled'] as bool? ?? true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'ticker': ticker,
      'name': name,
      'direction': direction,
      'leverage': leverage,
      'underlying': underlying,
      'expense_ratio': expenseRatio,
      'avg_daily_volume': avgDailyVolume,
      'enabled': enabled,
    };
  }
}

/// 섹터 레버리지 ETF 매핑 모델이다.
class SectorLeveraged {
  final String? bull;
  final String? bear;

  const SectorLeveraged({this.bull, this.bear});

  factory SectorLeveraged.fromJson(Map<String, dynamic> json) {
    return SectorLeveraged(
      bull: json['bull'] as String?,
      bear: json['bear'] as String?,
    );
  }
}

/// 섹터 데이터 모델이다.
class SectorData {
  final String key;
  final String nameKr;
  final String nameEn;
  final List<String> tickers;
  final SectorLeveraged? sectorLeveraged;
  final int enabledCount;
  final int totalCount;

  const SectorData({
    required this.key,
    required this.nameKr,
    required this.nameEn,
    required this.tickers,
    this.sectorLeveraged,
    required this.enabledCount,
    required this.totalCount,
  });

  factory SectorData.fromJson(Map<String, dynamic> json) {
    final rawTickers = json['tickers'];
    final List<String> tickerList;
    if (rawTickers is List) {
      tickerList = rawTickers.map((e) {
        if (e is String) return e;
        if (e is Map) return (e['ticker'] as String?) ?? e.toString();
        return e.toString();
      }).toList().cast<String>();
    } else {
      tickerList = [];
    }

    SectorLeveraged? leveraged;
    final rawLev = json['sector_leveraged'];
    if (rawLev is Map<String, dynamic>) {
      leveraged = SectorLeveraged.fromJson(rawLev);
    }

    return SectorData(
      key: json['sector_key'] as String? ?? '',
      nameKr: json['name_kr'] as String? ?? '',
      nameEn: json['name_en'] as String? ?? '',
      tickers: tickerList,
      sectorLeveraged: leveraged,
      enabledCount: (json['enabled'] as num? ?? 0).toInt(),
      totalCount: (json['total'] as num? ?? tickerList.length).toInt(),
    );
  }
}

class TickerMapping {
  final String underlying;
  final String? bull2x;
  final String? bear2x;

  TickerMapping({
    required this.underlying,
    this.bull2x,
    this.bear2x,
  });

  factory TickerMapping.fromJson(Map<String, dynamic> json) {
    return TickerMapping(
      underlying: json['underlying'] as String? ?? '',
      bull2x: json['bull_2x'] as String?,
      bear2x: json['bear_2x'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'underlying': underlying,
      'bull_2x': bull2x,
      'bear_2x': bear2x,
    };
  }
}

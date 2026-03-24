// 대시보드 관련 데이터 모델이다.

/// 안전한 DateTime 파싱 헬퍼이다. 실패 시 DateTime.now()를 반환한다.
DateTime _safeParseDatetime(dynamic raw) {
  if (raw == null) return DateTime.now();
  try {
    return DateTime.parse(raw as String);
  } catch (_) {
    return DateTime.now();
  }
}

class DashboardSummary {
  final double totalAsset;
  final double cash;
  final double todayPnl;
  final double todayPnlPct;
  final double cumulativeReturn;
  final int activePositions;
  final String systemStatus;
  final DateTime timestamp;

  // 미실현 손익 (보유 포지션 합산)
  final double unrealizedPnl;     // 미실현 손익 금액 (USD)
  final double unrealizedPnlPct;  // 미실현 손익 퍼센트 (%)

  // 전체 수익 (실현 + 미실현 합산)
  final double totalPnl;         // 전체 수익 금액 = cumulativeReturn + unrealizedPnl
  final double totalPnlPct;      // 전체 수익 퍼센트 (초기 자본 대비)
  final double initialCapital;   // 추정 초기 자본 = totalAsset - totalPnl

  // 상세 계좌 정보 필드
  final double positionsValue;   // 보유 포지션 평가금액 (total_asset - cash)
  final double buyingPower;      // 매수 가능 금액 (= cash)
  final String currency;         // 통화 단위 (예: "USD")
  final String accountNumber;    // 마스킹된 계좌번호 (예: "****7255-01")

  DashboardSummary({
    required this.totalAsset,
    required this.cash,
    required this.todayPnl,
    required this.todayPnlPct,
    required this.cumulativeReturn,
    required this.activePositions,
    required this.systemStatus,
    required this.timestamp,
    this.unrealizedPnl = 0.0,
    this.unrealizedPnlPct = 0.0,
    this.totalPnl = 0.0,
    this.totalPnlPct = 0.0,
    this.initialCapital = 0.0,
    this.positionsValue = 0.0,
    this.buyingPower = 0.0,
    this.currency = 'USD',
    this.accountNumber = '****0000-01',
  });

  factory DashboardSummary.fromJson(Map<String, dynamic> json) {
    final totalAsset = (json['total_asset'] as num? ?? 0).toDouble();
    final cash = (json['cash'] as num? ?? 0).toDouble();
    // 백엔드가 positions_value를 보내지 않으면 직접 계산한다
    final positionsValue = json['positions_value'] != null
        ? (json['positions_value'] as num).toDouble()
        : (totalAsset - cash).clamp(0.0, double.infinity);

    return DashboardSummary(
      totalAsset: totalAsset,
      cash: cash,
      todayPnl: (json['today_pnl'] as num? ?? 0).toDouble(),
      todayPnlPct: (json['today_pnl_pct'] as num? ?? 0).toDouble(),
      cumulativeReturn: (json['cumulative_return'] as num? ?? 0).toDouble(),
      activePositions: json['active_positions'] as int? ?? 0,
      systemStatus: json['system_status'] as String? ?? 'UNKNOWN',
      timestamp: _safeParseDatetime(json['timestamp']),
      unrealizedPnl: (json['unrealized_pnl'] as num? ?? 0).toDouble(),
      unrealizedPnlPct: (json['unrealized_pnl_pct'] as num? ?? 0).toDouble(),
      totalPnl: (json['total_pnl'] as num? ?? 0).toDouble(),
      totalPnlPct: (json['total_pnl_pct'] as num? ?? 0).toDouble(),
      initialCapital: (json['initial_capital'] as num? ?? 0).toDouble(),
      positionsValue: positionsValue,
      buyingPower: json['buying_power'] != null
          ? (json['buying_power'] as num).toDouble()
          : cash,
      currency: json['currency'] as String? ?? 'USD',
      accountNumber: json['account_number'] as String? ?? '****0000-01',
    );
  }
}

/// 백엔드 응답 예시:
/// {
///   "claude": {"status": "NORMAL"},
///   "kis": {"ok": true, "connected": true},
///   "database": {"ok": true},
///   "cache": {"ok": true},
///   "fallback": false,
///   "quota": {...},
///   "safety": {...},
///   "timestamp": "..."
/// }
class SystemStatus {
  final bool claude;
  final bool kis;
  final bool database;
  final bool cache;
  final bool fallback;
  final QuotaInfo quota;
  final SafetyInfo safety;
  final DateTime timestamp;

  SystemStatus({
    required this.claude,
    required this.kis,
    required this.database,
    required this.cache,
    required this.fallback,
    required this.quota,
    required this.safety,
    required this.timestamp,
  });

  factory SystemStatus.fromJson(Map<String, dynamic> json) {
    // claude 필드: 객체이거나 bool일 수 있다
    bool parseBool(dynamic value) {
      if (value == null) return false;
      if (value is bool) return value;
      if (value is Map) {
        // {"status": "NORMAL"} 또는 {"ok": true, "connected": true} 형식
        final status = value['status'] as String?;
        if (status != null) {
          return status.toUpperCase() != 'ERROR' && status.toUpperCase() != 'OFFLINE';
        }
        final ok = value['ok'] as bool?;
        final connected = value['connected'] as bool?;
        if (ok != null) return ok;
        if (connected != null) return connected;
        return true;
      }
      return false;
    }

    QuotaInfo quota;
    try {
      quota = QuotaInfo.fromJson(json['quota'] as Map<String, dynamic>? ?? {});
    } catch (_) {
      quota = QuotaInfo(
        claudeCallsToday: 0,
        claudeLimit: 100,
        kisCallsToday: 0,
        kisLimit: 1000,
      );
    }

    SafetyInfo safety;
    try {
      safety = SafetyInfo.fromJson(json['safety'] as Map<String, dynamic>? ?? {});
    } catch (_) {
      safety = SafetyInfo(
        stopLossEnabled: true,
        takeProfitEnabled: true,
        maxDrawdownCheck: true,
      );
    }

    return SystemStatus(
      claude: parseBool(json['claude']),
      kis: parseBool(json['kis']),
      database: parseBool(json['database']),
      cache: parseBool(json['cache'] ?? json['redis']),
      fallback: parseBool(json['fallback']),
      quota: quota,
      safety: safety,
      timestamp: _safeParseDatetime(json['timestamp']),
    );
  }
}

class QuotaInfo {
  final int claudeCallsToday;
  final int claudeLimit;
  final int kisCallsToday;
  final int kisLimit;

  // 백엔드 실제 필드
  final String mode;
  final int remaining;
  final double usagePct;
  final int windowHours;
  final bool canCall;

  QuotaInfo({
    required this.claudeCallsToday,
    required this.claudeLimit,
    required this.kisCallsToday,
    required this.kisLimit,
    this.mode = 'api',
    this.remaining = 0,
    this.usagePct = 0.0,
    this.windowHours = 5,
    this.canCall = true,
  });

  factory QuotaInfo.fromJson(Map<String, dynamic> json) {
    // 백엔드 실제 키: mode, remaining, usage_pct, calls_in_window,
    // max_calls, window_hours, can_call
    final callsInWindow = json['calls_in_window'] as int? ?? 0;
    final maxCalls = json['max_calls'] as int? ?? 225;
    return QuotaInfo(
      // calls_in_window를 오늘 호출 횟수로 매핑한다
      claudeCallsToday: callsInWindow,
      // max_calls를 한도로 매핑한다
      claudeLimit: maxCalls,
      kisCallsToday: json['kis_calls_today'] as int? ?? 0,
      kisLimit: json['kis_limit'] as int? ?? 1000,
      mode: json['mode'] as String? ?? 'api',
      remaining: json['remaining'] as int? ?? 0,
      usagePct: (json['usage_pct'] as num? ?? 0).toDouble(),
      windowHours: json['window_hours'] as int? ?? 5,
      canCall: json['can_call'] as bool? ?? true,
    );
  }
}

class SafetyInfo {
  final bool stopLossEnabled;
  final bool takeProfitEnabled;
  final bool maxDrawdownCheck;

  // 백엔드 실제 필드
  final bool isShutdown;
  final int dailyTrades;
  final int maxDailyTrades;
  final double dailyPnlPct;
  final double maxDailyLossPct;
  final double stopLossPct;
  final int maxHoldDays;
  final int vixShutdownThreshold;

  SafetyInfo({
    required this.stopLossEnabled,
    required this.takeProfitEnabled,
    required this.maxDrawdownCheck,
    this.isShutdown = false,
    this.dailyTrades = 0,
    this.maxDailyTrades = 30,
    this.dailyPnlPct = 0.0,
    this.maxDailyLossPct = -5.0,
    this.stopLossPct = -2.0,
    this.maxHoldDays = 5,
    this.vixShutdownThreshold = 35,
  });

  factory SafetyInfo.fromJson(Map<String, dynamic> json) {
    // 백엔드 실제 키: is_shutdown, daily_trades, max_daily_trades,
    // daily_pnl_pct, max_daily_loss_pct, stop_loss_pct,
    // max_hold_days, vix_shutdown_threshold
    final isShutdown = json['is_shutdown'] as bool? ?? false;
    return SafetyInfo(
      // is_shutdown=false이면 손절/익절 기능이 활성화된 것으로 판단한다
      stopLossEnabled: !isShutdown,
      takeProfitEnabled: json['take_profit_enabled'] as bool? ?? true,
      maxDrawdownCheck: json['max_drawdown_check'] as bool? ?? true,
      isShutdown: isShutdown,
      dailyTrades: json['daily_trades'] as int? ?? 0,
      maxDailyTrades: json['max_daily_trades'] as int? ?? 30,
      dailyPnlPct: (json['daily_pnl_pct'] as num? ?? 0).toDouble(),
      maxDailyLossPct:
          (json['max_daily_loss_pct'] as num? ?? -5.0).toDouble(),
      stopLossPct: (json['stop_loss_pct'] as num? ?? -2.0).toDouble(),
      maxHoldDays: json['max_hold_days'] as int? ?? 5,
      vixShutdownThreshold:
          json['vix_shutdown_threshold'] as int? ?? 35,
    );
  }
}

class AlertNotification {
  final String id;
  final String alertType;
  final String title;
  final String message;
  final String severity;
  final Map<String, dynamic>? data;
  final DateTime createdAt;
  final bool read;

  AlertNotification({
    required this.id,
    required this.alertType,
    required this.title,
    required this.message,
    required this.severity,
    this.data,
    required this.createdAt,
    required this.read,
  });

  factory AlertNotification.fromJson(Map<String, dynamic> json) {
    return AlertNotification(
      // 백엔드가 UUID 문자열로 id를 반환하므로 toString()으로 변환한다
      id: (json['id'] ?? '').toString(),
      // 백엔드가 'type' 키로 반환할 수 있으므로 폴백 처리한다
      alertType: json['alert_type'] as String? ?? json['type'] as String? ?? '',
      // title이 없으면 message를 title로 사용한다
      title: json['title'] as String? ?? json['message'] as String? ?? '',
      message: json['message'] as String? ?? '',
      severity: json['severity'] as String? ?? 'info',
      data: json['data'] as Map<String, dynamic>?,
      // 백엔드가 'timestamp' 키로 반환할 수 있으므로 폴백 처리한다
      createdAt: _safeParseDatetime(json['created_at'] ?? json['timestamp']),
      read: json['read'] as bool? ?? false,
    );
  }
}

class UniverseTicker {
  final String ticker;
  final String name;
  final String direction;
  final bool enabled;
  final String? underlying;
  final double? expenseRatio;
  final int? avgDailyVolume;
  final String? pairTicker;
  final String sector;
  final String exchange;
  final bool isInverse;
  final double leverage;

  UniverseTicker({
    required this.ticker,
    required this.name,
    required this.direction,
    required this.enabled,
    this.underlying,
    this.expenseRatio,
    this.avgDailyVolume,
    this.pairTicker,
    this.sector = '',
    this.exchange = 'AMS',
    this.isInverse = false,
    this.leverage = 2.0,
  });

  factory UniverseTicker.fromJson(Map<String, dynamic> json) {
    return UniverseTicker(
      ticker: json['ticker'] as String? ?? '',
      name: json['name'] as String? ?? '',
      direction: json['direction'] as String? ?? '',
      enabled: json['enabled'] as bool? ?? false,
      underlying: json['underlying'] as String?,
      expenseRatio: json['expense_ratio'] != null
          ? (json['expense_ratio'] as num).toDouble()
          : null,
      avgDailyVolume: json['avg_daily_volume'] as int?,
      pairTicker: json['pair_ticker'] as String?,
      sector: json['sector'] as String? ?? '',
      exchange: json['exchange'] as String? ?? 'AMS',
      isInverse: json['is_inverse'] as bool? ?? false,
      leverage: (json['leverage'] as num?)?.toDouble() ?? 2.0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'ticker': ticker,
      'name': name,
      'direction': direction,
      'enabled': enabled,
      'underlying': underlying,
      'expense_ratio': expenseRatio,
      'avg_daily_volume': avgDailyVolume,
      'pair_ticker': pairTicker,
      'sector': sector,
      'exchange': exchange,
      'is_inverse': isInverse,
      'leverage': leverage,
    };
  }
}

class CrawlStatus {
  final String taskId;
  final String status;
  final Map<String, dynamic>? data;

  // 상세 상태 필드 (CrawlDetailedStatusResponse에서 파싱)
  final int totalCrawlers;
  final int completedCrawlers;
  final double progressPct;
  final List<CrawlProgress> crawlerStatuses;

  CrawlStatus({
    required this.taskId,
    required this.status,
    this.data,
    this.totalCrawlers = 0,
    this.completedCrawlers = 0,
    this.progressPct = 0.0,
    this.crawlerStatuses = const [],
  });

  factory CrawlStatus.fromJson(Map<String, dynamic> json) {
    // crawler_statuses 배열을 파싱한다 (CrawlerStatusItem → CrawlProgress)
    final rawStatuses = json['crawler_statuses'] as List? ?? [];
    final crawlerStatuses = rawStatuses
        .map((e) => CrawlProgress.fromJson(e as Map<String, dynamic>))
        .toList();

    return CrawlStatus(
      taskId: json['task_id'] as String? ?? '',
      status: json['status'] as String? ?? '',
      data: json['data'] as Map<String, dynamic>?,
      totalCrawlers: (json['total_crawlers'] as num? ?? 0).toInt(),
      completedCrawlers: (json['completed_crawlers'] as num? ?? 0).toInt(),
      progressPct: (json['progress_pct'] as num? ?? 0.0).toDouble(),
      crawlerStatuses: crawlerStatuses,
    );
  }
}

/// 개별 크롤러의 진행 상태를 나타낸다.
/// WebSocket 및 폴링 이벤트를 모두 처리한다.
class CrawlProgress {
  /// 레거시 필드 (구버전 호환)
  final String source;
  final int articleCount;
  final String status;
  final double? timeElapsed;

  /// 신규 이벤트 필드
  final String? type;          // 'crawler_start' | 'crawler_done' | 'crawl_summary'
  final String? crawlerName;
  final int? crawlerIndex;
  final int? totalCrawlers;
  final String? message;
  final DateTime? timestamp;

  /// 원본 JSON 데이터 (crawl_summary 이벤트에서 CrawlSummary 파싱에 사용)
  final Map<String, dynamic>? rawJson;

  CrawlProgress({
    required this.source,
    required this.articleCount,
    required this.status,
    this.timeElapsed,
    this.type,
    this.crawlerName,
    this.crawlerIndex,
    this.totalCrawlers,
    this.message,
    this.timestamp,
    this.rawJson,
  });

  factory CrawlProgress.fromJson(Map<String, dynamic> json) {
    // 신규 이벤트 형식: crawler_name 또는 name 필드를 source로 사용한다
    // CrawlerStatusItem은 'name' 필드를 사용하고,
    // WebSocket 이벤트는 'crawler_name' 필드를 사용한다.
    final crawlerName = json['crawler_name'] as String?;
    final source = crawlerName
        ?? json['name'] as String?
        ?? json['source'] as String?
        ?? '';

    final rawCount = json['articles_count'] ?? json['article_count'];
    final articleCount = rawCount != null ? (rawCount as num).toInt() : 0;

    return CrawlProgress(
      source: source,
      articleCount: articleCount,
      status: json['status'] as String? ?? 'waiting',
      timeElapsed: json['time_elapsed'] != null
          ? (json['time_elapsed'] as num).toDouble()
          : null,
      type: json['type'] as String?,
      crawlerName: crawlerName,
      crawlerIndex: json['crawler_index'] as int?,
      totalCrawlers: json['total_crawlers'] as int?,
      message: json['message'] as String?,
      timestamp: json['timestamp'] != null
          ? DateTime.tryParse(json['timestamp'] as String)
          : null,
      rawJson: json,
    );
  }

  /// 상태를 변경한 새 인스턴스를 반환한다.
  CrawlProgress copyWith({
    String? status,
    int? articleCount,
    String? message,
    String? type,
  }) {
    return CrawlProgress(
      source: source,
      articleCount: articleCount ?? this.articleCount,
      status: status ?? this.status,
      timeElapsed: timeElapsed,
      type: type ?? this.type,
      crawlerName: crawlerName,
      crawlerIndex: crawlerIndex,
      totalCrawlers: totalCrawlers,
      message: message ?? this.message,
      timestamp: timestamp,
      rawJson: rawJson,
    );
  }
}

/// 크롤링 완료 후 최종 요약 데이터를 나타낸다.
class CrawlSummary {
  final int totalArticles;
  final int uniqueArticles;
  final int savedArticles;
  final int duplicatesRemoved;
  final double durationSeconds;
  final int successCount;
  final int failCount;
  final List<CrawlProgress> crawlerResults;

  CrawlSummary({
    required this.totalArticles,
    required this.uniqueArticles,
    required this.savedArticles,
    required this.duplicatesRemoved,
    required this.durationSeconds,
    required this.successCount,
    required this.failCount,
    required this.crawlerResults,
  });

  factory CrawlSummary.fromJson(Map<String, dynamic> json) {
    final rawResults = json['crawler_results'] as List? ?? [];
    final results = rawResults
        .map((e) => CrawlProgress.fromJson(e as Map<String, dynamic>))
        .toList();

    final successCount = results
        .where((r) => r.status.toLowerCase() == 'completed')
        .length;
    final failCount = results
        .where((r) => r.status.toLowerCase() == 'failed')
        .length;

    return CrawlSummary(
      totalArticles:
          (json['total_articles'] as num? ?? 0).toInt(),
      uniqueArticles:
          (json['unique_articles'] as num? ?? 0).toInt(),
      savedArticles:
          (json['saved_articles'] as num? ?? 0).toInt(),
      duplicatesRemoved:
          (json['duplicates_removed'] as num? ?? 0).toInt(),
      durationSeconds:
          (json['duration_seconds'] as num? ?? 0).toDouble(),
      successCount: successCount,
      failCount: failCount,
      crawlerResults: results,
    );
  }
}

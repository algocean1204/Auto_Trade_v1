// 긴급 프로토콜 관련 데이터 모델이다.
//
// 백엔드 EmergencyProtocol.get_status() 반환 구조:
// {
//   "circuit_breaker_active": bool,
//   "runaway_loss_shutdown": bool,
//   "flash_crash_cooldowns": {ticker: iso_string, ...},
// }

enum EmergencyState {
  active,   // 정상 트레이딩 중
  stopped,  // 긴급 정지됨 (서킷 브레이커 또는 runaway loss)
  cooldown, // 플래시 크래시 쿨다운 중
}

class EmergencyStatus {
  /// 서킷 브레이커 발동 여부 (VIX > 35 또는 SPY -3% 이상).
  final bool circuitBreakerActive;

  /// Runaway loss 셧다운 여부 (일일 손실 -5% 도달).
  final bool runawayLossShutdown;

  /// 플래시 크래시 쿨다운 중인 종목과 쿨다운 만료 시각 맵.
  final Map<String, DateTime> flashCrashCooldowns;

  EmergencyStatus({
    required this.circuitBreakerActive,
    required this.runawayLossShutdown,
    required this.flashCrashCooldowns,
  });

  /// 시스템이 어떤 형태로든 긴급 상태인지 반환한다.
  bool get isAnyEmergencyActive =>
      circuitBreakerActive ||
      runawayLossShutdown ||
      flashCrashCooldowns.isNotEmpty;

  EmergencyState get state {
    if (circuitBreakerActive || runawayLossShutdown) return EmergencyState.stopped;
    if (flashCrashCooldowns.isNotEmpty) return EmergencyState.cooldown;
    return EmergencyState.active;
  }

  /// 활성화된 긴급 상태의 요약 메시지를 반환한다.
  String get statusSummary {
    final parts = <String>[];
    if (circuitBreakerActive) parts.add('서킷 브레이커 발동');
    if (runawayLossShutdown) parts.add('일일 손실 한도 초과 셧다운');
    if (flashCrashCooldowns.isNotEmpty) {
      parts.add('플래시 크래시 쿨다운: ${flashCrashCooldowns.keys.join(', ')}');
    }
    return parts.isEmpty ? '정상' : parts.join(' | ');
  }

  factory EmergencyStatus.fromJson(Map<String, dynamic> json) {
    // flash_crash_cooldowns: {ticker: "2026-02-18T10:00:00+00:00", ...}
    final rawCooldowns = json['flash_crash_cooldowns'];
    final Map<String, DateTime> cooldowns = {};
    if (rawCooldowns is Map) {
      rawCooldowns.forEach((key, value) {
        if (value is String) {
          try {
            cooldowns[key as String] = DateTime.parse(value);
          } catch (_) {
            // 파싱 실패 시 무시한다
          }
        }
      });
    }

    return EmergencyStatus(
      circuitBreakerActive: json['circuit_breaker_active'] as bool? ?? false,
      runawayLossShutdown: json['runaway_loss_shutdown'] as bool? ?? false,
      flashCrashCooldowns: cooldowns,
    );
  }

  // API 실패 시 사용할 기본 안전 상태
  factory EmergencyStatus.defaultSafe() {
    return EmergencyStatus(
      circuitBreakerActive: false,
      runawayLossShutdown: false,
      flashCrashCooldowns: {},
    );
  }
}

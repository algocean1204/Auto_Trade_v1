// 세금 관련 데이터 모델이다.
//
// /tax/status 응답 구조:
// {
//   "year": int,
//   "summary": {
//     "total_gain_usd": float,
//     "total_loss_usd": float,
//     "net_gain_usd": float,
//     "net_gain_krw": float,
//     "exemption_krw": int,        // 2,500,000
//     "taxable_krw": float,
//     "estimated_tax_krw": float,
//     "tax_rate": float,           // 0.22
//   },
//   "remaining_exemption": {
//     "exemption_krw": int,
//     "used_krw": float,
//     "remaining_krw": float,
//     "utilization_pct": float,
//   }
// }

class TaxSummary {
  final double totalGainUsd;
  final double totalLossUsd;
  final double netGainUsd;
  final double netGainKrw;
  final double exemptionKrw;
  final double taxableKrw;
  final double estimatedTaxKrw;
  final double taxRate;

  TaxSummary({
    required this.totalGainUsd,
    required this.totalLossUsd,
    required this.netGainUsd,
    required this.netGainKrw,
    required this.exemptionKrw,
    required this.taxableKrw,
    required this.estimatedTaxKrw,
    required this.taxRate,
  });

  factory TaxSummary.fromJson(Map<String, dynamic> json) {
    return TaxSummary(
      totalGainUsd: (json['total_gain_usd'] as num? ?? 0).toDouble(),
      totalLossUsd: (json['total_loss_usd'] as num? ?? 0).toDouble(),
      netGainUsd: (json['net_gain_usd'] as num? ?? 0).toDouble(),
      netGainKrw: (json['net_gain_krw'] as num? ?? 0).toDouble(),
      exemptionKrw: (json['exemption_krw'] as num? ?? 2500000).toDouble(),
      taxableKrw: (json['taxable_krw'] as num? ?? 0).toDouble(),
      estimatedTaxKrw: (json['estimated_tax_krw'] as num? ?? 0).toDouble(),
      taxRate: (json['tax_rate'] as num? ?? 0.22).toDouble(),
    );
  }

  factory TaxSummary.empty() {
    return TaxSummary(
      totalGainUsd: 0,
      totalLossUsd: 0,
      netGainUsd: 0,
      netGainKrw: 0,
      exemptionKrw: 2500000,
      taxableKrw: 0,
      estimatedTaxKrw: 0,
      taxRate: 0.22,
    );
  }
}

class RemainingExemption {
  final double exemptionKrw;
  final double usedKrw;
  final double remainingKrw;
  final double utilizationPct;

  RemainingExemption({
    required this.exemptionKrw,
    required this.usedKrw,
    required this.remainingKrw,
    required this.utilizationPct,
  });

  factory RemainingExemption.fromJson(Map<String, dynamic> json) {
    return RemainingExemption(
      exemptionKrw: (json['exemption_krw'] as num? ?? 2500000).toDouble(),
      usedKrw: (json['used_krw'] as num? ?? 0).toDouble(),
      remainingKrw: (json['remaining_krw'] as num? ?? 2500000).toDouble(),
      utilizationPct: (json['utilization_pct'] as num? ?? 0).toDouble(),
    );
  }

  factory RemainingExemption.empty() {
    return RemainingExemption(
      exemptionKrw: 2500000,
      usedKrw: 0,
      remainingKrw: 2500000,
      utilizationPct: 0,
    );
  }
}

class TaxStatus {
  final int year;
  final TaxSummary summary;
  final RemainingExemption remainingExemption;

  TaxStatus({
    required this.year,
    required this.summary,
    required this.remainingExemption,
  });

  // 편의 접근자: 기존 코드 호환성을 위해 자주 사용되는 필드를 노출한다.
  double get realizedGainUsd => summary.netGainUsd;
  double get estimatedTaxKrw => summary.estimatedTaxKrw;
  // 백엔드는 KRW 기준 세금을 반환한다.
  // USD 환산이 필요한 화면에서는 KRW 값을 그대로 사용하거나 별도 변환을 적용한다.
  double get estimatedTaxUsd => summary.estimatedTaxKrw;
  double get taxRate => summary.taxRate;
  // 유효세율 (%)로 변환한다
  double get effectiveTaxRate => summary.taxRate * 100.0;
  // 백엔드가 taxResidency를 반환하지 않으므로 고정값을 사용한다.
  String get taxResidency => 'KR';
  double get remainingKrw => remainingExemption.remainingKrw;
  double get utilizationPct => remainingExemption.utilizationPct;

  factory TaxStatus.fromJson(Map<String, dynamic> json) {
    final summaryJson = json['summary'] as Map<String, dynamic>? ?? {};
    final remainingJson =
        json['remaining_exemption'] as Map<String, dynamic>? ?? {};

    return TaxStatus(
      year: json['year'] as int? ?? DateTime.now().year,
      summary: TaxSummary.fromJson(summaryJson),
      remainingExemption: RemainingExemption.fromJson(remainingJson),
    );
  }

  factory TaxStatus.empty() {
    return TaxStatus(
      year: DateTime.now().year,
      summary: TaxSummary.empty(),
      remainingExemption: RemainingExemption.empty(),
    );
  }
}

class TaxHarvestSuggestion {
  final String ticker;
  final double unrealizedLossUsd;
  final double potentialTaxSavingKrw;
  final String recommendation;

  TaxHarvestSuggestion({
    required this.ticker,
    required this.unrealizedLossUsd,
    required this.potentialTaxSavingKrw,
    required this.recommendation,
  });

  factory TaxHarvestSuggestion.fromJson(Map<String, dynamic> json) {
    return TaxHarvestSuggestion(
      ticker: json['ticker'] as String? ?? '',
      // 백엔드 필드: 'unrealized_loss_usd'
      unrealizedLossUsd: (json['unrealized_loss_usd'] as num? ??
              json['unrealized_loss'] as num? ??
              0)
          .toDouble(),
      // 백엔드 필드: 'potential_tax_saving_krw'
      potentialTaxSavingKrw: (json['potential_tax_saving_krw'] as num? ??
              json['potential_saving'] as num? ??
              0)
          .toDouble(),
      // 백엔드 필드: 'recommendation'
      recommendation: json['recommendation'] as String? ??
          json['reason'] as String? ??
          '',
    );
  }
}

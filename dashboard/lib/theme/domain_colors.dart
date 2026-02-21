import 'package:flutter/material.dart';

/// 도메인 특화 시맨틱 색상 상수를 정의한다.
/// 모델 계층에서 사용하는 비즈니스 도메인 색상(감성, 카테고리, 신호 등)을
/// 하드코딩 없이 중앙에서 관리한다.
class DomainColors {
  DomainColors._();

  // ── 감성/방향 색상 (Sentiment / Direction) ──
  /// 강세 (bullish) - green
  static const Color bullish = Color(0xFF10B981);

  /// 약세 (bearish) - red
  static const Color bearish = Color(0xFFEF4444);

  /// 중립 (neutral / default) - gray
  static const Color neutral = Color(0xFF6B7280);

  // ── 영향도 색상 (Impact) ──
  /// 높은 영향 (high impact) - red
  static const Color impactHigh = Color(0xFFEF4444);

  /// 보통 영향 (medium impact) - amber
  static const Color impactMedium = Color(0xFFF59E0B);

  /// 낮은 영향 (low impact / default) - gray
  static const Color impactLow = Color(0xFF6B7280);

  // ── 매매 신호 색상 (Trade Signal) ──
  /// 매수 (buy) - green
  static const Color signalBuy = Color(0xFF10B981);

  /// 매도 (sell) - red
  static const Color signalSell = Color(0xFFEF4444);

  /// 보유 (hold) - amber
  static const Color signalHold = Color(0xFFF59E0B);

  // ── 기술적 점수 색상 (Score / Composite) ──
  /// 긍정 점수 (score > 0.3) - green
  static const Color scorePositive = Color(0xFF10B981);

  /// 부정 점수 (score < -0.3) - red
  static const Color scoreNegative = Color(0xFFEF4444);

  /// 중립 점수 - amber
  static const Color scoreNeutral = Color(0xFFF59E0B);

  // ── RSI 상태 색상 ──
  /// RSI 과매수 (>70) - red
  static const Color rsiOverbought = Color(0xFFEF4444);

  /// RSI 과매도 (<30) - green
  static const Color rsiOversold = Color(0xFF10B981);

  /// RSI 중립 - medium gray (테마 무관 중립색)
  static const Color rsiNeutral = Color(0xFF6B7280);

  // ── 가격 변동 색상 ──
  /// 가격 상승 - green
  static const Color priceUp = Color(0xFF10B981);

  /// 가격 하락 - red
  static const Color priceDown = Color(0xFFEF4444);

  // ── 뉴스 카테고리 색상 (News Category) ──
  /// 매크로 - blue
  static const Color categoryMacro = Color(0xFF3B82F6);

  /// 실적 (earnings) - green
  static const Color categoryEarnings = Color(0xFF10B981);

  /// 기업 (company) - purple
  static const Color categoryCompany = Color(0xFF8B5CF6);

  /// 섹터 (sector) - teal
  static const Color categorySector = Color(0xFF14B8A6);

  /// 정책 (policy) - indigo
  static const Color categoryPolicy = Color(0xFF6366F1);

  /// 지정학 (geopolitics) - orange
  static const Color categoryGeopolitics = Color(0xFFF97316);

  /// 기타 (other / default) - gray
  static const Color categoryOther = Color(0xFF6B7280);

  // ── 매매 원칙 카테고리 색상 (Principle Category) ──
  /// 생존 (survival) - red
  static const Color principleSurvival = Color(0xFFEF4444);

  /// 리스크 (risk) - amber
  static const Color principleRisk = Color(0xFFF59E0B);

  /// 전략 (strategy) - blue
  static const Color principleStrategy = Color(0xFF3B82F6);

  /// 실행 (execution) - green
  static const Color principleExecution = Color(0xFF10B981);

  /// 마인드셋 (mindset) - purple
  static const Color principleMindset = Color(0xFF8B5CF6);

  /// 사용자 정의 (custom) - teal
  static const Color principleCustom = Color(0xFF14B8A6);

  // ── 거래 상태 색상 (Trade Status) ──
  /// 미체결 (open) - blue
  static const Color statusOpen = Color(0xFF3B82F6);

  // ── 분석 뉴스 영향도 색상 (AnalysisNews Impact) ──
  /// 분석 뉴스 높은 영향 - red
  static const Color analysisImpactHigh = Color(0xFFEF4444);

  /// 분석 뉴스 보통 영향 - amber
  static const Color analysisImpactMedium = Color(0xFFF59E0B);

  /// 분석 뉴스 낮은 영향 - medium gray (테마 무관 중립색)
  static const Color analysisImpactLow = Color(0xFF9CA3AF);
}

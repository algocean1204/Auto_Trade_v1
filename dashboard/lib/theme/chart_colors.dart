import 'package:flutter/material.dart';

/// 도메인 특화 차트/시각화에서 사용하는 색상 상수를 정의한다.
/// 테마(다크/라이트)와 무관하게 의미론적으로 고정된 값이므로 상수로 관리한다.
class ChartColors {
  ChartColors._();

  // ── RSI 지표 색상 ──
  /// RSI(7) 단기 - orange
  static const Color rsi7 = Color(0xFFF59E0B);

  /// RSI(14) 표준 - blue
  static const Color rsi14 = Color(0xFF3B82F6);

  /// RSI(21) 중기 - purple
  static const Color rsi21 = Color(0xFF8B5CF6);

  // ── RSI 구간 색상 ──
  /// 과매도 구간 (0-30) - blue
  static const Color rsiOversold = Color(0xFF3B82F6);

  /// 약세 구간 (30-40) - orange
  static const Color rsiBearish = Color(0xFFF97316);

  /// 중립 구간 (40-60) - gray
  static const Color rsiNeutral = Color(0xFF6B7280);

  /// 강세 구간 (60-70) - green
  static const Color rsiBullish = Color(0xFF10B981);

  /// 과매수 구간 (70-100) - red
  static const Color rsiOverbought = Color(0xFFEF4444);

  // ── Fear & Greed 지수 색상 ──
  /// 극도의 공포 (0-20/25) - red
  static const Color fearExtreme = Color(0xFFEF4444);

  /// 공포 (20-40/25-45) - orange
  static const Color fear = Color(0xFFF97316);

  /// 중립 (40-60/45-55) - yellow
  static const Color fearNeutral = Color(0xFFEAB308);

  /// 탐욕 (60-80/55-75) - lime green
  static const Color greed = Color(0xFF84CC16);

  /// 극도의 탐욕 (80-100/75-100) - green
  static const Color greedExtreme = Color(0xFF22C55E);

  // ── CPI 차트 색상 ──
  /// CPI 추세선 색상 - orange
  static const Color cpiLine = Color(0xFFFB923C);

  /// CPI Fed 목표선 색상 - amber
  static const Color cpiFedTarget = Color(0xFFFBBF24);

  // ── 금리 차트 색상 ──
  /// 금리 추세선 - indigo
  static const Color rateLine = Color(0xFF6366F1);

  /// 금리 현재값 라인 - indigo accent
  static const Color rateCurrentLine = Color(0xFF818CF8);

  // ── 기타 도메인 색상 ──
  /// VIX 높은 불안 - red-orange
  static const Color vixHighAnxiety = Color(0xFFF97316);

  /// 보라색 (chart4) 계열 - 시장 국면, 실업률 등 범용 보라색
  static const Color purple = Color(0xFF8B5CF6);

  // ── 카테고리 악센트 색상 (RSI 화면 카테고리) ──
  /// 빅테크 카테고리 - blue
  static const Color categoryBigTech = Color(0xFF3B82F6);

  /// 지수 ETF 카테고리 - green
  static const Color categoryIndex = Color(0xFF10B981);

  /// 섹터 ETF 카테고리 - purple
  static const Color categorySector = Color(0xFF8B5CF6);

  /// 관심종목 카테고리 - amber
  static const Color categoryWatchlist = Color(0xFFF59E0B);

  /// Fear & Greed 게이지에서 점수에 따른 색상을 반환한다 (5단계 그라디언트).
  static Color colorForFearGreedScore(double score) {
    if (score <= 20) return fearExtreme;
    if (score <= 40) return fear;
    if (score <= 60) return fearNeutral;
    if (score <= 80) return greed;
    return greedExtreme;
  }

  /// Fear & Greed 차트에서 점수에 따른 임계값 색상을 반환한다.
  static Color colorForFearGreedThreshold(double score) {
    if (score <= 25) return fearExtreme;
    if (score <= 45) return fear;
    if (score <= 55) return fearNeutral;
    if (score <= 75) return greed;
    return greedExtreme;
  }
}

import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../models/macro_models.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// Fear & Greed 임계값 기준선이 표시되는 라인 차트 위젯이다.
/// 히스토리 데이터가 없을 경우 현재 값을 단일 포인트로 표시하고
/// 5개의 구간 기준선을 항상 렌더링한다.
class FearGreedChart extends StatelessWidget {
  /// 현재 Fear & Greed 지수이다.
  final FearGreedIndex fearGreed;

  /// 과거 데이터 포인트 목록이다 (선택적).
  /// 각 포인트는 (날짜 라벨, 점수) 쌍으로 구성된다.
  final List<FearGreedDataPoint>? history;

  const FearGreedChart({
    super.key,
    required this.fearGreed,
    this.history,
  });

  // ── 임계값 색상 상수 (ChartColors 참조) ──
  static const Color _extremeFearColor = ChartColors.fearExtreme;
  static const Color _fearColor = ChartColors.fear;
  static const Color _neutralColor = ChartColors.fearNeutral;
  static const Color _greedColor = ChartColors.greed;
  static const Color _extremeGreedColor = ChartColors.greedExtreme;

  /// 점수에 따른 임계값 색상을 반환한다.
  static Color colorForScore(double score) {
    return ChartColors.colorForFearGreedThreshold(score);
  }

  @override
  Widget build(BuildContext context) {
    final spots = _buildSpots();
    final currentScore = fearGreed.score.toDouble();
    final scoreColor = colorForScore(currentScore);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildLegendRow(),
        AppSpacing.vGapMd,
        SizedBox(
          height: 260,
          child: Padding(
            padding: const EdgeInsets.only(right: 16),
            child: LineChart(
              LineChartData(
                minY: 0,
                maxY: 100,
                clipData: const FlClipData.all(),
                gridData: FlGridData(
                  show: true,
                  drawVerticalLine: false,
                  horizontalInterval: 25,
                  getDrawingHorizontalLine: (value) => FlLine(
                    color: context.tc.chartGrid,
                    strokeWidth: 0.5,
                  ),
                ),
                borderData: FlBorderData(show: false),
                titlesData: FlTitlesData(
                  leftTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: true,
                      interval: 25,
                      reservedSize: 32,
                      getTitlesWidget: (value, meta) {
                        if (value % 25 != 0) return const SizedBox.shrink();
                        return Padding(
                          padding: const EdgeInsets.only(right: 4),
                          child: Text(
                            value.toInt().toString(),
                            style: AppTypography.bodySmall.copyWith(fontSize: 11),
                            textAlign: TextAlign.right,
                          ),
                        );
                      },
                    ),
                  ),
                  rightTitles: const AxisTitles(
                    sideTitles: SideTitles(showTitles: false),
                  ),
                  topTitles: const AxisTitles(
                    sideTitles: SideTitles(showTitles: false),
                  ),
                  bottomTitles: AxisTitles(
                    sideTitles: SideTitles(
                      showTitles: _hasHistory,
                      reservedSize: 20,
                      getTitlesWidget: (value, meta) {
                        if (!_hasHistory) return const SizedBox.shrink();
                        final items = history ?? [];
                        final idx = value.toInt();
                        if (idx < 0 || idx >= items.length) {
                          return const SizedBox.shrink();
                        }
                        final step = (items.length / 4).ceil().clamp(1, 999);
                        if (idx % step != 0) return const SizedBox.shrink();
                        return Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            items[idx].label,
                            style: AppTypography.bodySmall.copyWith(fontSize: 11),
                          ),
                        );
                      },
                    ),
                  ),
                ),
                extraLinesData: ExtraLinesData(
                  horizontalLines: [
                    // 극심한 공포 경계 (Y=25)
                    HorizontalLine(
                      y: 25,
                      color: _extremeFearColor.withValues(alpha: 0.55),
                      strokeWidth: 1,
                      dashArray: [5, 4],
                      label: HorizontalLineLabel(
                        show: true,
                        alignment: Alignment.topRight,
                        labelResolver: (_) => ' 극심한 공포',
                        style: TextStyle(
                          color: _extremeFearColor.withValues(alpha: 0.75),
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    // 공포 경계 (Y=45)
                    HorizontalLine(
                      y: 45,
                      color: _fearColor.withValues(alpha: 0.55),
                      strokeWidth: 1,
                      dashArray: [5, 4],
                      label: HorizontalLineLabel(
                        show: true,
                        alignment: Alignment.topRight,
                        labelResolver: (_) => ' 공포',
                        style: TextStyle(
                          color: _fearColor.withValues(alpha: 0.75),
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    // 중립 경계 (Y=55)
                    HorizontalLine(
                      y: 55,
                      color: _neutralColor.withValues(alpha: 0.55),
                      strokeWidth: 1,
                      dashArray: [5, 4],
                      label: HorizontalLineLabel(
                        show: true,
                        alignment: Alignment.topRight,
                        labelResolver: (_) => ' 중립',
                        style: TextStyle(
                          color: _neutralColor.withValues(alpha: 0.75),
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    // 탐욕 경계 (Y=75)
                    HorizontalLine(
                      y: 75,
                      color: _greedColor.withValues(alpha: 0.55),
                      strokeWidth: 1,
                      dashArray: [5, 4],
                      label: HorizontalLineLabel(
                        show: true,
                        alignment: Alignment.topRight,
                        labelResolver: (_) => ' 탐욕',
                        style: TextStyle(
                          color: _greedColor.withValues(alpha: 0.75),
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                  ],
                ),
                lineBarsData: [
                  LineChartBarData(
                    spots: spots,
                    isCurved: spots.length > 2,
                    curveSmoothness: 0.3,
                    color: scoreColor,
                    barWidth: spots.length == 1 ? 0 : 3.5,
                    isStrokeCapRound: true,
                    dotData: FlDotData(
                      show: true,
                      getDotPainter: (spot, percent, bar, index) {
                        // 단일 포인트이거나 마지막 포인트일 때만 점을 강조한다
                        final isLast = index == spots.length - 1;
                        if (spots.length == 1 || isLast) {
                          return FlDotCirclePainter(
                            radius: spots.length == 1 ? 6 : 4,
                            color: scoreColor,
                            strokeWidth: 2,
                            strokeColor: context.tc.background,
                          );
                        }
                        return FlDotCirclePainter(
                          radius: 0,
                          color: Colors.transparent,
                          strokeWidth: 0,
                          strokeColor: Colors.transparent,
                        );
                      },
                    ),
                    belowBarData: BarAreaData(
                      show: true,
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [
                          scoreColor.withValues(alpha: 0.12),
                          scoreColor.withValues(alpha: 0.02),
                        ],
                      ),
                    ),
                  ),
                ],
                lineTouchData: LineTouchData(
                  enabled: _hasHistory,
                  touchTooltipData: LineTouchTooltipData(
                    getTooltipColor: (_) =>
                        context.tc.surfaceElevated.withValues(alpha: 0.95),
                    getTooltipItems: (touchedSpots) {
                      return touchedSpots.map((spot) {
                        final idx = spot.spotIndex;
                        final hist = history;
                        final label = _hasHistory && hist != null && idx < hist.length
                            ? hist[idx].label
                            : '';
                        final score = spot.y.toInt();
                        final c = colorForScore(spot.y);
                        return LineTooltipItem(
                          label.isNotEmpty ? '$label\n$score' : '$score',
                          AppTypography.bodySmall.copyWith(
                            color: c,
                            fontSize: 10,
                            height: 1.5,
                          ),
                        );
                      }).toList();
                    },
                  ),
                ),
              ),
            ),
          ),
        ),
        // 현재 값 표시 행
        AppSpacing.vGapSm,
        _buildCurrentValueRow(currentScore, scoreColor, context),
      ],
    );
  }

  bool get _hasHistory => history != null && (history?.isNotEmpty ?? false);

  List<FlSpot> _buildSpots() {
    final hist = history;
    if (_hasHistory && hist != null) {
      return hist
          .asMap()
          .entries
          .map((e) => FlSpot(e.key.toDouble(), e.value.score.clamp(0, 100)))
          .toList();
    }
    // 히스토리가 없으면 현재 값을 중앙에 단일 포인트로 표시한다
    return [FlSpot(0, fearGreed.score.toDouble().clamp(0, 100))];
  }

  Widget _buildLegendRow() {
    final zones = [
      (color: _extremeFearColor, label: '극심한 공포', range: '0–25'),
      (color: _fearColor, label: '공포', range: '25–45'),
      (color: _neutralColor, label: '중립', range: '45–55'),
      (color: _greedColor, label: '탐욕', range: '55–75'),
      (color: _extremeGreedColor, label: '극심한 탐욕', range: '75–100'),
    ];

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: zones.map((z) {
          return Padding(
            padding: const EdgeInsets.only(right: 10),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: z.color,
                    shape: BoxShape.circle,
                  ),
                ),
                AppSpacing.hGapXs,
                Text(
                  z.label,
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 11,
                    color: z.color.withValues(alpha: 0.85),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildCurrentValueRow(double score, Color color, BuildContext context) {
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.10),
            borderRadius: AppSpacing.borderRadiusMd,
            border: Border.all(color: color.withValues(alpha: 0.30), width: 1),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  color: color,
                  shape: BoxShape.circle,
                ),
              ),
              AppSpacing.hGapXs,
              Text(
                '현재 지수',
                style: AppTypography.bodySmall.copyWith(
                  fontSize: 10,
                  color: context.tc.textTertiary,
                ),
              ),
              AppSpacing.hGapSm,
              Text(
                score.toInt().toString(),
                style: AppTypography.numberSmall.copyWith(
                  color: color,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        if (!_hasHistory) ...[
          AppSpacing.hGapSm,
          Text(
            '히스토리 데이터 미제공',
            style: AppTypography.bodySmall.copyWith(
              fontSize: 9,
              color: context.tc.textDisabled,
            ),
          ),
        ],
      ],
    );
  }
}

/// Fear & Greed 히스토리 데이터 포인트이다.
class FearGreedDataPoint {
  /// X축에 표시할 날짜 라벨이다.
  final String label;

  /// 0–100 범위의 Fear & Greed 점수이다.
  final double score;

  const FearGreedDataPoint({required this.label, required this.score});
}

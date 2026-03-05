import 'package:flutter/material.dart';
import '../models/macro_models.dart';
import '../theme/trading_colors.dart';
import '../theme/chart_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

/// 거시경제 핵심 지표 4개를 가로로 나열한 컴팩트 카드 행이다.
/// 기준금리 / CPI / 실업률 / 장단기 금리차를 표시한다.
class MacroStatsRow extends StatelessWidget {
  final MacroIndicators indicators;

  const MacroStatsRow({super.key, required this.indicators});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final cards = _buildCards(context);
        final isNarrow = constraints.maxWidth < 480;
        if (isNarrow) {
          return Wrap(
            spacing: 8,
            runSpacing: 8,
            children: cards,
          );
        }
        // 2x2 grid layout
        return Column(
          children: [
            Row(
              children: [
                Expanded(child: cards[0]),
                const SizedBox(width: 8),
                Expanded(child: cards[1]),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(child: cards[2]),
                const SizedBox(width: 8),
                Expanded(child: cards[3]),
              ],
            ),
          ],
        );
      },
    );
  }

  List<Widget> _buildCards(BuildContext context) {
    final fedRate = indicators.fedRate;
    final cpi = indicators.cpi;
    final unemp = indicators.unemployment;
    final spread = indicators.treasurySpread;

    return [
      _buildStatCard(
        icon: Icons.account_balance_rounded,
        iconColor: Colors.indigo,
        label: '기준금리',
        value: '${fedRate.value.toStringAsFixed(2)}%',
        sublabel: fedRate.targetRange,
        changeValue: null,
        interpretation: _fedRateInterpretation(fedRate.value),
        interpretationColor: _fedRateInterpretationColor(fedRate.value, context),
        context: context,
      ),
      _buildStatCard(
        icon: Icons.show_chart_rounded,
        iconColor: Colors.orange,
        label: 'CPI YoY',
        value: '${cpi.value.toStringAsFixed(1)}%',
        sublabel: cpi.releaseDate,
        changeValue: cpi.change,
        interpretation: _cpiInterpretation(cpi.value),
        interpretationColor: _cpiInterpretationColor(cpi.value, context),
        context: context,
      ),
      _buildStatCard(
        icon: Icons.people_rounded,
        iconColor: ChartColors.purple,
        label: '실업률',
        value: '${unemp.value.toStringAsFixed(1)}%',
        sublabel: null,
        changeValue: unemp.change,
        interpretation: _unemploymentInterpretation(unemp.value),
        interpretationColor: _unemploymentInterpretationColor(unemp.value, context),
        context: context,
      ),
      _buildStatCard(
        icon: Icons.swap_vert_rounded,
        iconColor: _spreadColor(spread.signal, context),
        label: '장단기 금리차',
        value: '${spread.value >= 0 ? '+' : ''}${spread.value.toStringAsFixed(2)}%',
        sublabel: _spreadLabel(spread.signal),
        changeValue: null,
        interpretation: _spreadInterpretation(spread.signal),
        interpretationColor: _spreadColor(spread.signal, context),
        context: context,
      ),
    ];
  }

  // ── Fed Rate ──

  String _fedRateInterpretation(double rate) {
    if (rate < 2.0) return '완화적 통화정책 - 성장주/레버리지 유리';
    if (rate < 4.0) return '중립적 금리 수준';
    if (rate < 5.0) return '긴축적 - 고금리 부담 주의';
    return '강한 긴축 - 성장주 압박 가능';
  }

  Color _fedRateInterpretationColor(double rate, BuildContext context) {
    if (rate < 2.0) return context.tc.profit;
    if (rate < 4.0) return context.tc.textTertiary;
    if (rate < 5.0) return context.tc.warning;
    return context.tc.loss;
  }

  // ── CPI ──

  String _cpiInterpretation(double cpi) {
    if (cpi < 2.0) return '인플레이션 안정 - 금리 인하 가능성';
    if (cpi < 3.0) return '목표 범위 내 - 안정적';
    if (cpi < 4.0) return '인플레이션 경계 - 금리 동결/인상 가능';
    return '높은 인플레이션 - 긴축 압력';
  }

  Color _cpiInterpretationColor(double cpi, BuildContext context) {
    if (cpi < 2.0) return context.tc.profit;
    if (cpi < 3.0) return context.tc.textTertiary;
    if (cpi < 4.0) return context.tc.warning;
    return context.tc.loss;
  }

  // ── Unemployment ──

  String _unemploymentInterpretation(double rate) {
    if (rate < 4.0) return '완전고용 수준 - 경기 호조';
    if (rate < 5.0) return '자연실업률 수준 - 보통';
    if (rate < 6.0) return '고용 둔화 - 경기 하락 신호';
    return '높은 실업률 - 경기 침체 우려';
  }

  Color _unemploymentInterpretationColor(double rate, BuildContext context) {
    if (rate < 4.0) return context.tc.profit;
    if (rate < 5.0) return context.tc.textTertiary;
    if (rate < 6.0) return context.tc.warning;
    return context.tc.loss;
  }

  // ── Treasury Spread ──

  Color _spreadColor(String signal, BuildContext context) {
    switch (signal) {
      case 'inverted':
        return context.tc.loss;
      case 'flattening':
        return context.tc.warning;
      default:
        return context.tc.profit;
    }
  }

  String _spreadLabel(String signal) {
    switch (signal) {
      case 'inverted':
        return '역전';
      case 'flattening':
        return '평탄화';
      default:
        return '정상';
    }
  }

  String _spreadInterpretation(String signal) {
    switch (signal) {
      case 'inverted':
        return '수익률 곡선 역전 - 경기 침체 경고 (12-18개월 선행)';
      case 'flattening':
        return '수익률 곡선 평탄화 - 경기 둔화 신호';
      default:
        return '정상적 수익률 곡선 - 경기 확장 기대';
    }
  }

  Widget _buildStatCard({
    required IconData icon,
    required Color iconColor,
    required String label,
    required String value,
    String? sublabel,
    double? changeValue,
    required String interpretation,
    required Color interpretationColor,
    required BuildContext context,
  }) {
    final hasChange = changeValue != null && changeValue != 0;
    final changeColor = hasChange
        ? (changeValue > 0 ? context.tc.loss : context.tc.profit)
        : context.tc.textTertiary;
    final changeArrow = hasChange
        ? (changeValue > 0
            ? Icons.arrow_upward_rounded
            : Icons.arrow_downward_rounded)
        : null;

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: context.tc.surface.withValues(alpha: 0.7),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: context.tc.surfaceBorder, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: iconColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Icon(icon, size: 22, color: iconColor),
              ),
              AppSpacing.hGapXs,
              Expanded(
                child: Text(
                  label,
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 14,
                    color: context.tc.textTertiary,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          AppSpacing.vGapXs,
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Text(
                value,
                style: AppTypography.numberSmall.copyWith(
                  color: context.tc.textPrimary,
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                ),
              ),
              if (hasChange && changeArrow != null) ...[
                AppSpacing.hGapXs,
                Icon(changeArrow, size: 13, color: changeColor),
                Text(
                  changeValue.abs().toStringAsFixed(1),
                  style: AppTypography.bodySmall.copyWith(
                    color: changeColor,
                    fontSize: 12,
                  ),
                ),
              ],
            ],
          ),
          if (sublabel != null)
            Text(
              sublabel,
              style: AppTypography.bodySmall.copyWith(
                fontSize: 12,
                color: context.tc.textDisabled,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          AppSpacing.vGapXs,
          // 해석 텍스트
          Text(
            interpretation,
            style: AppTypography.bodySmall.copyWith(
              fontSize: 13,
              color: interpretationColor.withValues(alpha: 0.85),
              height: 1.3,
            ),
            overflow: TextOverflow.ellipsis,
            maxLines: 4,
          ),
        ],
      ),
    );
  }
}

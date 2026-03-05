import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../providers/manual_trade_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../theme/trading_colors.dart';
import '../widgets/confirmation_dialog.dart';

/// 수동 매매 요청 화면이다.
///
/// 종목 코드 + 수량 입력 → AI 분석 → 확인 → 실행 흐름을 제공한다.
class ManualTradeScreen extends StatelessWidget {
  const ManualTradeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      backgroundColor: tc.background,
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 헤더
            _buildHeader(context, tc, t),
            const SizedBox(height: 24),
            // 입력 폼 + 결과를 가로 배치
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 왼쪽: 입력 폼
                SizedBox(
                  width: 380,
                  child: _buildInputForm(context, tc, t),
                ),
                const SizedBox(width: 24),
                // 오른쪽: 분석 결과 / 실행 결과
                Expanded(
                  child: _buildResultArea(context, tc, t),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader(BuildContext context, TradingColors tc, String Function(String) t) {
    return Row(
      children: [
        Icon(Icons.swap_horiz_rounded, size: 28, color: tc.primary),
        AppSpacing.hGapMd,
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t('manual_trade_title'), style: AppTypography.displaySmall),
            const SizedBox(height: 2),
            Text(
              t('manual_trade_desc'),
              style: AppTypography.bodySmall.copyWith(color: tc.textSecondary),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildInputForm(BuildContext context, TradingColors tc, String Function(String) t) {
    return Consumer<ManualTradeProvider>(
      builder: (context, provider, _) {
        return Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            color: tc.surface,
            borderRadius: AppSpacing.borderRadiusLg,
            border: Border.all(color: tc.surfaceBorder.withValues(alpha: 0.3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // 종목 코드 입력
              Text(
                t('manual_trade_ticker'),
                style: AppTypography.labelLarge.copyWith(color: tc.textPrimary),
              ),
              const SizedBox(height: 8),
              TextField(
                onChanged: provider.setTicker,
                decoration: InputDecoration(
                  hintText: t('manual_trade_ticker_hint'),
                  hintStyle: AppTypography.bodyMedium.copyWith(color: tc.textTertiary),
                  filled: true,
                  fillColor: tc.surfaceElevated,
                  border: OutlineInputBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                    borderSide: BorderSide(color: tc.surfaceBorder),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                    borderSide: BorderSide(color: tc.surfaceBorder.withValues(alpha: 0.5)),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: AppSpacing.borderRadiusMd,
                    borderSide: BorderSide(color: tc.primary, width: 1.5),
                  ),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                ),
                style: AppTypography.numberMedium.copyWith(color: tc.textPrimary),
                textCapitalization: TextCapitalization.characters,
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z]')),
                  LengthLimitingTextInputFormatter(10),
                ],
              ),
              const SizedBox(height: 20),

              // 매매 방향 선택
              Text(
                t('manual_trade_side'),
                style: AppTypography.labelLarge.copyWith(color: tc.textPrimary),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: _SideButton(
                      label: t('manual_trade_buy'),
                      icon: Icons.arrow_upward_rounded,
                      isSelected: provider.side == 'buy',
                      color: tc.profit,
                      onTap: () => provider.setSide('buy'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _SideButton(
                      label: t('manual_trade_sell'),
                      icon: Icons.arrow_downward_rounded,
                      isSelected: provider.side == 'sell',
                      color: tc.loss,
                      onTap: () => provider.setSide('sell'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),

              // 수량 입력
              Text(
                t('manual_trade_quantity'),
                style: AppTypography.labelLarge.copyWith(color: tc.textPrimary),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  // 감소 버튼
                  _QuantityButton(
                    icon: Icons.remove,
                    onTap: provider.quantity > 1
                        ? () => provider.setQuantity(provider.quantity - 1)
                        : null,
                    tc: tc,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                      controller: TextEditingController(
                        text: provider.quantity.toString(),
                      )..selection = TextSelection.fromPosition(
                          TextPosition(offset: provider.quantity.toString().length),
                        ),
                      onChanged: (val) {
                        final parsed = int.tryParse(val);
                        if (parsed != null && parsed > 0) {
                          provider.setQuantity(parsed);
                        }
                      },
                      textAlign: TextAlign.center,
                      keyboardType: TextInputType.number,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: tc.surfaceElevated,
                        border: OutlineInputBorder(
                          borderRadius: AppSpacing.borderRadiusMd,
                          borderSide: BorderSide(color: tc.surfaceBorder),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: AppSpacing.borderRadiusMd,
                          borderSide: BorderSide(color: tc.surfaceBorder.withValues(alpha: 0.5)),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: AppSpacing.borderRadiusMd,
                          borderSide: BorderSide(color: tc.primary, width: 1.5),
                        ),
                        contentPadding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                      style: AppTypography.numberMedium.copyWith(color: tc.textPrimary),
                    ),
                  ),
                  const SizedBox(width: 12),
                  // 증가 버튼
                  _QuantityButton(
                    icon: Icons.add,
                    onTap: () => provider.setQuantity(provider.quantity + 1),
                    tc: tc,
                  ),
                ],
              ),
              const SizedBox(height: 8),
              // 빠른 수량 버튼
              Row(
                children: [1, 5, 10, 20, 50].map((q) {
                  return Expanded(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 2),
                      child: OutlinedButton(
                        onPressed: () => provider.setQuantity(q),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: provider.quantity == q ? tc.primary : tc.textSecondary,
                          side: BorderSide(
                            color: provider.quantity == q
                                ? tc.primary.withValues(alpha: 0.5)
                                : tc.surfaceBorder.withValues(alpha: 0.4),
                          ),
                          backgroundColor: provider.quantity == q
                              ? tc.primary.withValues(alpha: 0.08)
                              : Colors.transparent,
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          shape: RoundedRectangleBorder(
                            borderRadius: AppSpacing.borderRadiusSm,
                          ),
                        ),
                        child: Text(
                          '$q',
                          style: AppTypography.bodySmall.copyWith(
                            fontSize: 12,
                            color: provider.quantity == q ? tc.primary : tc.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  );
                }).toList(),
              ),
              const SizedBox(height: 24),

              // 분석 요청 버튼
              SizedBox(
                height: 48,
                child: ElevatedButton.icon(
                  onPressed: provider.isAnalyzing || provider.ticker.isEmpty
                      ? null
                      : () => provider.analyzeRequest(),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: tc.primary,
                    foregroundColor: Colors.white,
                    disabledBackgroundColor: tc.primary.withValues(alpha: 0.3),
                    shape: RoundedRectangleBorder(
                      borderRadius: AppSpacing.borderRadiusMd,
                    ),
                    elevation: 0,
                  ),
                  icon: provider.isAnalyzing
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.psychology_rounded, size: 20),
                  label: Text(
                    provider.isAnalyzing
                        ? t('manual_trade_analyzing')
                        : t('manual_trade_analyze'),
                    style: AppTypography.labelLarge.copyWith(color: Colors.white),
                  ),
                ),
              ),

              // 에러 메시지
              if (provider.analyzeError != null) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: tc.loss.withValues(alpha: 0.08),
                    borderRadius: AppSpacing.borderRadiusMd,
                    border: Border.all(color: tc.loss.withValues(alpha: 0.3)),
                  ),
                  child: Text(
                    provider.analyzeError!,
                    style: AppTypography.bodySmall.copyWith(color: tc.loss),
                  ),
                ),
              ],

              const SizedBox(height: 16),

              // 초기화 버튼
              TextButton.icon(
                onPressed: () => provider.reset(),
                icon: Icon(Icons.refresh_rounded, size: 16, color: tc.textSecondary),
                label: Text(
                  t('manual_trade_reset'),
                  style: AppTypography.bodySmall.copyWith(color: tc.textSecondary),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildResultArea(BuildContext context, TradingColors tc, String Function(String) t) {
    return Consumer<ManualTradeProvider>(
      builder: (context, provider, _) {
        // 실행 완료 결과
        if (provider.executeResult != null) {
          return _buildExecuteResult(context, tc, t, provider);
        }

        // 분석 결과
        if (provider.analysisResult != null) {
          return _buildAnalysisResult(context, tc, t, provider);
        }

        // 초기 상태 (안내 메시지)
        return _buildEmptyState(tc, t);
      },
    );
  }

  Widget _buildEmptyState(TradingColors tc, String Function(String) t) {
    return Container(
      padding: const EdgeInsets.all(40),
      decoration: BoxDecoration(
        color: tc.surface,
        borderRadius: AppSpacing.borderRadiusLg,
        border: Border.all(color: tc.surfaceBorder.withValues(alpha: 0.2)),
      ),
      child: Center(
        child: Column(
          children: [
            Icon(
              Icons.swap_horiz_rounded,
              size: 64,
              color: tc.textTertiary.withValues(alpha: 0.3),
            ),
            const SizedBox(height: 16),
            Text(
              t('manual_trade_title'),
              style: AppTypography.labelLarge.copyWith(color: tc.textSecondary),
            ),
            const SizedBox(height: 8),
            Text(
              t('manual_trade_desc'),
              style: AppTypography.bodySmall.copyWith(color: tc.textTertiary),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAnalysisResult(
    BuildContext context,
    TradingColors tc,
    String Function(String) t,
    ManualTradeProvider provider,
  ) {
    final result = provider.analysisResult!;
    final aiOpinion = result['ai_opinion'] as Map<String, dynamic>? ?? {};
    final technical = result['technical_summary'] as Map<String, dynamic>? ?? {};
    final holding = result['holding'] as Map<String, dynamic>?;
    final fmt = NumberFormat.currency(symbol: '\$', decimalDigits: 2);

    final opinion = (aiOpinion['opinion'] ?? 'neutral') as String;
    final confidence = (aiOpinion['confidence'] ?? 0) as int;
    final reasoning = (aiOpinion['reasoning'] ?? '') as String;
    final risks = (aiOpinion['risks'] as List<dynamic>?)?.cast<String>() ?? [];
    final suggestion = (aiOpinion['suggestion'] ?? '') as String;
    final aiAvailable = (aiOpinion['available'] ?? false) as bool;

    // 의견에 따른 색상
    Color opinionColor;
    String opinionLabel;
    IconData opinionIcon;
    switch (opinion) {
      case 'agree':
        opinionColor = tc.profit;
        opinionLabel = t('manual_trade_agree');
        opinionIcon = Icons.thumb_up_rounded;
        break;
      case 'disagree':
        opinionColor = tc.loss;
        opinionLabel = t('manual_trade_disagree');
        opinionIcon = Icons.thumb_down_rounded;
        break;
      default:
        opinionColor = tc.warning;
        opinionLabel = t('manual_trade_neutral');
        opinionIcon = Icons.thumbs_up_down_rounded;
    }

    return Column(
      children: [
        // 가격 및 금액 정보 카드
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: tc.surface,
            borderRadius: AppSpacing.borderRadiusLg,
            border: Border.all(color: tc.surfaceBorder.withValues(alpha: 0.3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  // 종목 + 방향
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: (provider.side == 'buy' ? tc.profit : tc.loss)
                          .withValues(alpha: 0.12),
                      borderRadius: AppSpacing.borderRadiusSm,
                    ),
                    child: Text(
                      '${result['ticker']} ${provider.side == 'buy' ? t('manual_trade_buy') : t('manual_trade_sell')}',
                      style: AppTypography.labelLarge.copyWith(
                        color: provider.side == 'buy' ? tc.profit : tc.loss,
                      ),
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${provider.quantity}${t('shares')}',
                    style: AppTypography.numberMedium.copyWith(color: tc.textPrimary),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              // 현재가 / 예상 금액
              Row(
                children: [
                  _InfoTile(
                    label: t('manual_trade_current_price'),
                    value: fmt.format(result['current_price'] ?? 0),
                    tc: tc,
                  ),
                  const SizedBox(width: 24),
                  _InfoTile(
                    label: t('manual_trade_estimated_cost'),
                    value: fmt.format(result['estimated_cost'] ?? 0),
                    tc: tc,
                  ),
                ],
              ),
              // 보유 현황
              if (holding != null) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: tc.info.withValues(alpha: 0.06),
                    borderRadius: AppSpacing.borderRadiusSm,
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.inventory_2_outlined, size: 14, color: tc.info),
                      const SizedBox(width: 6),
                      Text(
                        '${t('manual_trade_holding')}: ${holding['quantity']}${t('shares')} @ ${fmt.format(holding['avg_price'] ?? 0)}',
                        style: AppTypography.bodySmall.copyWith(color: tc.info),
                      ),
                      const Spacer(),
                      Text(
                        '${((holding['pnl_pct'] ?? 0) as num).toStringAsFixed(2)}%',
                        style: AppTypography.numberSmall.copyWith(
                          color: tc.pnlColor((holding['pnl_pct'] ?? 0).toDouble()),
                        ),
                      ),
                    ],
                  ),
                ),
              ] else ...[
                const SizedBox(height: 12),
                Text(
                  t('manual_trade_not_holding'),
                  style: AppTypography.bodySmall.copyWith(color: tc.textTertiary),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),

        // AI 의견 카드
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: tc.surface,
            borderRadius: AppSpacing.borderRadiusLg,
            border: Border.all(
              color: aiAvailable
                  ? opinionColor.withValues(alpha: 0.3)
                  : tc.surfaceBorder.withValues(alpha: 0.3),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // AI 의견 헤더
              Row(
                children: [
                  Icon(Icons.psychology_rounded, size: 20, color: tc.primary),
                  const SizedBox(width: 8),
                  Text(
                    t('manual_trade_ai_opinion'),
                    style: AppTypography.labelLarge.copyWith(color: tc.textPrimary),
                  ),
                  const Spacer(),
                  if (aiAvailable)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: opinionColor.withValues(alpha: 0.12),
                        borderRadius: AppSpacing.borderRadiusFull,
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(opinionIcon, size: 14, color: opinionColor),
                          const SizedBox(width: 4),
                          Text(
                            '$opinionLabel ($confidence%)',
                            style: AppTypography.labelMedium.copyWith(
                              color: opinionColor,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              // 분석 근거
              if (reasoning.isNotEmpty)
                Text(
                  reasoning,
                  style: AppTypography.bodyMedium.copyWith(
                    color: tc.textPrimary,
                    height: 1.5,
                  ),
                ),
              // 리스크
              if (risks.isNotEmpty) ...[
                const SizedBox(height: 12),
                ...risks.map((r) => Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Icon(Icons.warning_amber_rounded, size: 14, color: tc.warning),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              r,
                              style: AppTypography.bodySmall.copyWith(color: tc.textSecondary),
                            ),
                          ),
                        ],
                      ),
                    )),
              ],
              // 제안
              if (suggestion.isNotEmpty) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: tc.primary.withValues(alpha: 0.06),
                    borderRadius: AppSpacing.borderRadiusSm,
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.lightbulb_outline_rounded, size: 14, color: tc.primary),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          suggestion,
                          style: AppTypography.bodySmall.copyWith(color: tc.primary),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),

        // 기술적 지표 카드
        if (technical['available'] == true)
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: tc.surface,
              borderRadius: AppSpacing.borderRadiusLg,
              border: Border.all(color: tc.surfaceBorder.withValues(alpha: 0.3)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  t('manual_trade_technical'),
                  style: AppTypography.labelLarge.copyWith(color: tc.textPrimary),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    _TechBadge(
                      label: 'RSI(14)',
                      value: '${technical['rsi_14'] ?? 'N/A'}',
                      color: _rsiColor(tc, technical['rsi_14']),
                      tc: tc,
                    ),
                    const SizedBox(width: 12),
                    _TechBadge(
                      label: 'MACD',
                      value: '${technical['macd_signal'] ?? 'N/A'}',
                      color: technical['macd_signal'] == 'bullish' ? tc.profit : tc.loss,
                      tc: tc,
                    ),
                    const SizedBox(width: 12),
                    _TechBadge(
                      label: 'Trend',
                      value: '${technical['trend'] ?? 'N/A'}',
                      color: technical['trend'] == 'uptrend'
                          ? tc.profit
                          : technical['trend'] == 'downtrend'
                              ? tc.loss
                              : tc.warning,
                      tc: tc,
                    ),
                  ],
                ),
              ],
            ),
          ),
        const SizedBox(height: 24),

        // 실행 버튼
        if (provider.canExecute)
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton.icon(
              onPressed: () => _handleExecute(context, provider, t),
              style: ElevatedButton.styleFrom(
                backgroundColor: provider.side == 'buy' ? tc.profit : tc.loss,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                elevation: 0,
              ),
              icon: Icon(
                provider.side == 'buy'
                    ? Icons.arrow_upward_rounded
                    : Icons.arrow_downward_rounded,
                size: 22,
              ),
              label: Text(
                t('manual_trade_execute'),
                style: AppTypography.labelLarge.copyWith(
                  color: Colors.white,
                  fontSize: 16,
                ),
              ),
            ),
          ),

        // 실행 에러
        if (provider.executeError != null) ...[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: tc.loss.withValues(alpha: 0.08),
              borderRadius: AppSpacing.borderRadiusMd,
              border: Border.all(color: tc.loss.withValues(alpha: 0.3)),
            ),
            child: Text(
              provider.executeError!,
              style: AppTypography.bodySmall.copyWith(color: tc.loss),
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildExecuteResult(
    BuildContext context,
    TradingColors tc,
    String Function(String) t,
    ManualTradeProvider provider,
  ) {
    final result = provider.executeResult!;
    final fmt = NumberFormat.currency(symbol: '\$', decimalDigits: 2);
    final isBuy = (result['side'] ?? 'buy') == 'buy';

    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: tc.surface,
        borderRadius: AppSpacing.borderRadiusLg,
        border: Border.all(
          color: (isBuy ? tc.profit : tc.loss).withValues(alpha: 0.3),
        ),
      ),
      child: Column(
        children: [
          // 성공 아이콘
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: (isBuy ? tc.profit : tc.loss).withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: Icon(
              Icons.check_rounded,
              size: 36,
              color: isBuy ? tc.profit : tc.loss,
            ),
          ),
          const SizedBox(height: 16),
          Text(
            t('manual_trade_success'),
            style: AppTypography.labelLarge.copyWith(
              color: tc.textPrimary,
              fontSize: 18,
            ),
          ),
          const SizedBox(height: 24),
          // 실행 상세
          _ResultRow(label: t('ticker'), value: result['ticker'] ?? '', tc: tc),
          _ResultRow(
            label: t('manual_trade_side'),
            value: isBuy ? t('manual_trade_buy') : t('manual_trade_sell'),
            tc: tc,
            valueColor: isBuy ? tc.profit : tc.loss,
          ),
          _ResultRow(
            label: t('manual_trade_quantity'),
            value: '${result['quantity'] ?? 0}',
            tc: tc,
          ),
          _ResultRow(
            label: t('manual_trade_current_price'),
            value: fmt.format(result['price'] ?? 0),
            tc: tc,
          ),
          _ResultRow(
            label: t('manual_trade_order_id'),
            value: result['order_id'] ?? '',
            tc: tc,
          ),
          const SizedBox(height: 24),
          // 새 거래 버튼
          OutlinedButton.icon(
            onPressed: () => provider.reset(),
            icon: Icon(Icons.add_rounded, size: 18, color: tc.primary),
            label: Text(
              t('manual_trade_reset'),
              style: AppTypography.labelMedium.copyWith(color: tc.primary),
            ),
            style: OutlinedButton.styleFrom(
              side: BorderSide(color: tc.primary.withValues(alpha: 0.4)),
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.borderRadiusMd,
              ),
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            ),
          ),
        ],
      ),
    );
  }

  Color _rsiColor(TradingColors tc, dynamic rsi) {
    if (rsi == null) return tc.textSecondary;
    final val = (rsi is num) ? rsi.toDouble() : 50.0;
    if (val >= 70) return tc.loss;
    if (val <= 30) return tc.profit;
    return tc.warning;
  }

  Future<void> _handleExecute(
    BuildContext context,
    ManualTradeProvider provider,
    String Function(String) t,
  ) async {
    final tc = context.tc;
    final sideLabel = provider.side == 'buy'
        ? t('manual_trade_buy')
        : t('manual_trade_sell');

    final confirmed = await ConfirmationDialog.show(
      context,
      title: t('manual_trade_confirm_title'),
      message: '${provider.ticker} ${provider.quantity}주를 $sideLabel하시겠습니까?',
      confirmLabel: sideLabel,
      cancelLabel: t('cancel'),
      confirmColor: provider.side == 'buy' ? tc.profit : tc.loss,
      icon: provider.side == 'buy'
          ? Icons.arrow_upward_rounded
          : Icons.arrow_downward_rounded,
    );

    if (confirmed && context.mounted) {
      await provider.executeTrade();
      if (context.mounted) {
        if (provider.executeError != null) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('${t('manual_trade_failed')}: ${provider.executeError}'),
              backgroundColor: tc.loss,
            ),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(t('manual_trade_success')),
              backgroundColor: tc.profit,
            ),
          );
        }
      }
    }
  }
}

// ── 보조 위젯 ──

class _SideButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool isSelected;
  final Color color;
  final VoidCallback onTap;

  const _SideButton({
    required this.label,
    required this.icon,
    required this.isSelected,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: AppSpacing.borderRadiusMd,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: isSelected ? color.withValues(alpha: 0.12) : Colors.transparent,
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(
            color: isSelected ? color.withValues(alpha: 0.5) : context.tc.surfaceBorder.withValues(alpha: 0.4),
            width: isSelected ? 1.5 : 1,
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 18, color: isSelected ? color : context.tc.textSecondary),
            const SizedBox(width: 6),
            Text(
              label,
              style: AppTypography.labelLarge.copyWith(
                color: isSelected ? color : context.tc.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuantityButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback? onTap;
  final TradingColors tc;

  const _QuantityButton({
    required this.icon,
    required this.onTap,
    required this.tc,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: AppSpacing.borderRadiusMd,
      child: Container(
        width: 40,
        height: 48,
        decoration: BoxDecoration(
          color: tc.surfaceElevated,
          borderRadius: AppSpacing.borderRadiusMd,
          border: Border.all(color: tc.surfaceBorder.withValues(alpha: 0.5)),
        ),
        child: Icon(icon, size: 18, color: onTap != null ? tc.textPrimary : tc.textTertiary),
      ),
    );
  }
}

class _InfoTile extends StatelessWidget {
  final String label;
  final String value;
  final TradingColors tc;

  const _InfoTile({
    required this.label,
    required this.value,
    required this.tc,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: AppTypography.bodySmall.copyWith(color: tc.textTertiary, fontSize: 11)),
        const SizedBox(height: 2),
        Text(value, style: AppTypography.numberMedium.copyWith(color: tc.textPrimary)),
      ],
    );
  }
}

class _TechBadge extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  final TradingColors tc;

  const _TechBadge({
    required this.label,
    required this.value,
    required this.color,
    required this.tc,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: AppSpacing.borderRadiusMd,
        border: Border.all(color: color.withValues(alpha: 0.2)),
      ),
      child: Column(
        children: [
          Text(label, style: AppTypography.bodySmall.copyWith(color: tc.textTertiary, fontSize: 10)),
          const SizedBox(height: 2),
          Text(value, style: AppTypography.labelMedium.copyWith(color: color, fontSize: 12)),
        ],
      ),
    );
  }
}

class _ResultRow extends StatelessWidget {
  final String label;
  final String value;
  final TradingColors tc;
  final Color? valueColor;

  const _ResultRow({
    required this.label,
    required this.value,
    required this.tc,
    this.valueColor,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: AppTypography.bodySmall.copyWith(color: tc.textSecondary)),
          Text(
            value,
            style: AppTypography.labelMedium.copyWith(
              color: valueColor ?? tc.textPrimary,
            ),
          ),
        ],
      ),
    );
  }
}

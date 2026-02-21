import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/dashboard_models.dart';
import '../providers/universe_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';

// ── 신규: 종목 자동 추가 다이얼로그 ──────────────────────────────────────────────

/// 종목 코드 하나만 입력하면 Claude가 정보를 자동으로 조회해 추가하는 다이얼로그이다.
class TickerAddDialog extends StatefulWidget {
  const TickerAddDialog({super.key});

  @override
  State<TickerAddDialog> createState() => _TickerAddDialogState();
}

class _TickerAddDialogState extends State<TickerAddDialog> {
  final _tickerController = TextEditingController();
  bool _isLoading = false;
  String? _errorMessage;
  Map<String, dynamic>? _result;

  @override
  void dispose() {
    _tickerController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final ticker = _tickerController.text.trim().toUpperCase();
    if (ticker.isEmpty) return;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _result = null;
    });

    try {
      final result =
          await context.read<UniverseProvider>().autoAddTicker(ticker);
      if (mounted) {
        setState(() {
          _isLoading = false;
          _result = result;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _errorMessage = e.toString().replaceFirst('Exception: ', '');
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;
    final tc = context.tc;

    // 결과 화면
    if (_result != null) {
      return _buildResultDialog(context, tc, t);
    }

    // 입력 화면
    return _buildInputDialog(context, tc, t);
  }

  /// 종목 코드 입력 다이얼로그를 빌드한다.
  Widget _buildInputDialog(
      BuildContext context, TradingColors tc, String Function(String) t) {
    return AlertDialog(
      backgroundColor: tc.surfaceElevated,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusLg,
        side: BorderSide(
          color: tc.surfaceBorder.withValues(alpha: 0.4),
          width: 1,
        ),
      ),
      title: Row(
        children: [
          Icon(Icons.add_circle_outline_rounded, color: tc.primary, size: 22),
          AppSpacing.hGapSm,
          Text(t('auto_add_ticker'), style: AppTypography.headlineMedium),
        ],
      ),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              t('enter_ticker_code'),
              style: AppTypography.labelMedium
                  .copyWith(color: tc.textSecondary),
            ),
            AppSpacing.vGapSm,
            TextField(
              controller: _tickerController,
              autofocus: true,
              textCapitalization: TextCapitalization.characters,
              enabled: !_isLoading,
              style: AppTypography.displaySmall.copyWith(
                color: tc.textPrimary,
                letterSpacing: 2,
              ),
              decoration: InputDecoration(
                hintText: 'NVDA',
                hintStyle: AppTypography.displaySmall.copyWith(
                  color: tc.textDisabled,
                  letterSpacing: 2,
                ),
                filled: true,
                fillColor: tc.surface,
                border: OutlineInputBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                  borderSide: BorderSide(
                      color: tc.surfaceBorder.withValues(alpha: 0.3)),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                  borderSide: BorderSide(
                      color: tc.surfaceBorder.withValues(alpha: 0.3)),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                  borderSide:
                      BorderSide(color: tc.primary.withValues(alpha: 0.6), width: 1.5),
                ),
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              ),
              onSubmitted: (_) => _isLoading ? null : _submit(),
            ),
            // 로딩 상태 표시
            if (_isLoading) ...[
              AppSpacing.vGapMd,
              Row(
                children: [
                  SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: tc.primary,
                    ),
                  ),
                  AppSpacing.hGapSm,
                  Expanded(
                    child: Text(
                      t('claude_researching'),
                      style: AppTypography.bodySmall
                          .copyWith(color: tc.primary),
                    ),
                  ),
                ],
              ),
            ],
            // 에러 메시지
            if (_errorMessage != null) ...[
              AppSpacing.vGapMd,
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: tc.loss.withValues(alpha: 0.08),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: tc.loss.withValues(alpha: 0.25),
                    width: 1,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(Icons.error_outline_rounded,
                        size: 16, color: tc.loss),
                    AppSpacing.hGapSm,
                    Expanded(
                      child: Text(
                        _errorMessage ?? '',
                        style: AppTypography.bodySmall
                            .copyWith(color: tc.loss),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _isLoading ? null : () => Navigator.pop(context),
          child: Text(
            t('cancel'),
            style: AppTypography.labelLarge
                .copyWith(color: tc.textSecondary),
          ),
        ),
        ElevatedButton(
          onPressed: _isLoading ? null : _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: tc.primary,
            foregroundColor: Colors.white,
            disabledBackgroundColor: tc.primary.withValues(alpha: 0.4),
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusSm,
            ),
          ),
          child: _isLoading
              ? SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : Text(
                  t('add_ticker'),
                  style: AppTypography.labelLarge
                      .copyWith(color: Colors.white),
                ),
        ),
      ],
    );
  }

  /// 추가 완료 결과 다이얼로그를 빌드한다.
  Widget _buildResultDialog(
      BuildContext context, TradingColors tc, String Function(String) t) {
    final result = _result ?? {};
    final ticker = result['ticker'] as String? ?? '';
    final name = result['name'] as String? ?? '';
    final sectorNameKr = result['sector_name_kr'] as String? ?? '';
    final bull2x = result['bull_2x_etf'] as String?;
    final bear2x = result['bear_2x_etf'] as String?;
    final sectorBull = result['sector_bull_etf'] as String?;
    final sectorBear = result['sector_bear_etf'] as String?;

    return AlertDialog(
      backgroundColor: tc.surfaceElevated,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusLg,
        side: BorderSide(
          color: tc.profit.withValues(alpha: 0.4),
          width: 1,
        ),
      ),
      title: Row(
        children: [
          Icon(Icons.check_circle_outline_rounded,
              color: tc.profit, size: 22),
          AppSpacing.hGapSm,
          Text(t('add_complete'), style: AppTypography.headlineMedium),
        ],
      ),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 종목 헤더
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: tc.surface,
                borderRadius: AppSpacing.borderRadiusMd,
                border: Border.all(
                  color: tc.surfaceBorder.withValues(alpha: 0.3),
                  width: 1,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$ticker${name.isNotEmpty ? ' - $name' : ''}',
                    style: AppTypography.labelLarge
                        .copyWith(fontSize: 15, color: tc.textPrimary),
                  ),
                  if (sectorNameKr.isNotEmpty) ...[
                    AppSpacing.vGapXs,
                    Text(
                      '섹터: $sectorNameKr',
                      style: AppTypography.bodySmall
                          .copyWith(color: tc.textSecondary),
                    ),
                  ],
                ],
              ),
            ),
            AppSpacing.vGapMd,
            // ETF 매핑 정보
            if (bull2x != null || bear2x != null) ...[
              _buildEtfRow(
                context,
                tc,
                label: t('leveraged_etf'),
                bull: bull2x,
                bear: bear2x,
              ),
              AppSpacing.vGapSm,
            ],
            if (sectorBull != null || sectorBear != null)
              _buildEtfRow(
                context,
                tc,
                label: t('sector_etf'),
                bull: sectorBull,
                bear: sectorBear,
              ),
            if (bull2x == null && bear2x == null && sectorBull == null && sectorBear == null)
              Text(
                t('no_leveraged'),
                style: AppTypography.bodySmall
                    .copyWith(color: tc.textTertiary),
              ),
          ],
        ),
      ),
      actions: [
        ElevatedButton(
          onPressed: () => Navigator.pop(context, true),
          style: ElevatedButton.styleFrom(
            backgroundColor: tc.profit,
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusSm,
            ),
          ),
          child: Text(
            t('confirm'),
            style:
                AppTypography.labelLarge.copyWith(color: Colors.white),
          ),
        ),
      ],
    );
  }

  /// Bull/Bear ETF 행을 빌드한다.
  Widget _buildEtfRow(
    BuildContext context,
    TradingColors tc, {
    required String label,
    String? bull,
    String? bear,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        SizedBox(
          width: 72,
          child: Text(
            label,
            style: AppTypography.bodySmall.copyWith(color: tc.textTertiary),
          ),
        ),
        AppSpacing.hGapSm,
        if (bull != null)
          _etfBadge(tc, bull, tc.profit, '▲'),
        if (bull != null && bear != null)
          AppSpacing.hGapSm,
        if (bear != null)
          _etfBadge(tc, bear, tc.loss, '▼'),
      ],
    );
  }

  Widget _etfBadge(TradingColors tc, String label, Color color, String prefix) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: AppSpacing.borderRadiusSm,
        border: Border.all(
          color: color.withValues(alpha: 0.30),
          width: 1,
        ),
      ),
      child: Text(
        '$prefix $label',
        style: AppTypography.labelMedium.copyWith(
          fontSize: 11,
          color: color,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

// ── 기존 다이얼로그 (레거시, 삭제하지 않음) ────────────────────────────────────────

/// 기존 복잡한 5-필드 입력 방식의 다이얼로그이다.
/// 하위 호환성 유지를 위해 보존한다.
class TickerAddDialogLegacy extends StatefulWidget {
  final String direction;

  const TickerAddDialogLegacy({super.key, required this.direction});

  @override
  State<TickerAddDialogLegacy> createState() => _TickerAddDialogLegacyState();
}

class _TickerAddDialogLegacyState extends State<TickerAddDialogLegacy> {
  final _formKey = GlobalKey<FormState>();
  final _tickerController = TextEditingController();
  final _nameController = TextEditingController();
  final _underlyingController = TextEditingController();
  final _expenseRatioController = TextEditingController();
  final _volumeController = TextEditingController();
  bool _enabled = true;

  @override
  void dispose() {
    _tickerController.dispose();
    _nameController.dispose();
    _underlyingController.dispose();
    _expenseRatioController.dispose();
    _volumeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    final isBull = widget.direction == 'bull';

    return AlertDialog(
      backgroundColor: tc.surfaceElevated,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusLg,
        side: BorderSide(
          color: tc.surfaceBorder.withValues(alpha: 0.4),
          width: 1,
        ),
      ),
      title: Row(
        children: [
          Icon(
            isBull ? Icons.trending_up_rounded : Icons.trending_down_rounded,
            color: isBull ? tc.profit : tc.loss,
            size: 22,
          ),
          AppSpacing.hGapSm,
          Text(
            '${isBull ? 'Bull' : 'Bear'} 2X ETF',
            style: AppTypography.headlineMedium,
          ),
        ],
      ),
      content: SingleChildScrollView(
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _buildField(
                controller: _tickerController,
                label: 'Ticker *',
                hint: 'TQQQ',
                validator: (value) {
                  if (value == null || value.isEmpty) return 'Required';
                  return null;
                },
              ),
              AppSpacing.vGapMd,
              _buildField(
                controller: _nameController,
                label: 'Name *',
                hint: 'ProShares UltraPro QQQ',
                validator: (value) {
                  if (value == null || value.isEmpty) return 'Required';
                  return null;
                },
              ),
              AppSpacing.vGapMd,
              _buildField(
                controller: _underlyingController,
                label: 'Underlying',
                hint: 'QQQ',
              ),
              AppSpacing.vGapMd,
              _buildField(
                controller: _expenseRatioController,
                label: 'Expense Ratio (%)',
                hint: '0.95',
                keyboardType: TextInputType.number,
              ),
              AppSpacing.vGapMd,
              _buildField(
                controller: _volumeController,
                label: 'Avg Daily Volume',
                hint: '50000000',
                keyboardType: TextInputType.number,
              ),
              AppSpacing.vGapLg,
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                decoration: BoxDecoration(
                  color: tc.surface,
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: tc.surfaceBorder.withValues(alpha: 0.3),
                    width: 1,
                  ),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Enabled', style: AppTypography.bodyMedium),
                    Switch(
                      value: _enabled,
                      onChanged: (value) => setState(() => _enabled = value),
                      activeColor: tc.primary,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(
            'Cancel',
            style: AppTypography.labelLarge.copyWith(
              color: tc.textSecondary,
            ),
          ),
        ),
        ElevatedButton(
          onPressed: _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: tc.primary,
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.borderRadiusSm,
            ),
          ),
          child: Text(
            'Add',
            style: AppTypography.labelLarge.copyWith(color: Colors.white),
          ),
        ),
      ],
    );
  }

  Widget _buildField({
    required TextEditingController controller,
    required String label,
    required String hint,
    TextInputType? keyboardType,
    String? Function(String?)? validator,
  }) {
    return TextFormField(
      controller: controller,
      keyboardType: keyboardType,
      validator: validator,
      style: AppTypography.bodyMedium.copyWith(color: context.tc.textPrimary),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle:
            AppTypography.bodySmall.copyWith(color: context.tc.textTertiary),
        hintStyle:
            AppTypography.bodySmall.copyWith(color: context.tc.textDisabled),
      ),
    );
  }

  void _submit() {
    if (_formKey.currentState?.validate() ?? false) {
      final ticker = UniverseTicker(
        ticker: _tickerController.text.trim().toUpperCase(),
        name: _nameController.text.trim(),
        direction: widget.direction,
        enabled: _enabled,
        underlying: _underlyingController.text.trim().isNotEmpty
            ? _underlyingController.text.trim()
            : null,
        expenseRatio: _expenseRatioController.text.trim().isNotEmpty
            ? double.tryParse(_expenseRatioController.text.trim())
            : null,
        avgDailyVolume: _volumeController.text.trim().isNotEmpty
            ? int.tryParse(_volumeController.text.trim())
            : null,
      );
      Navigator.pop(context, ticker);
    }
  }
}

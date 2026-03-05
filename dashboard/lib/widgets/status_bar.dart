import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/dashboard_provider.dart';
import '../providers/tax_fx_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../animations/animation_utils.dart';

/// 화면 하단 상태 바이다. 시스템 상태, FX 환율, 다음 분석 시각을 표시한다.
class StatusBar extends StatelessWidget {
  const StatusBar({super.key});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Container(
      height: 32,
      decoration: BoxDecoration(
        color: tc.surface,
        border: Border(
          top: BorderSide(
            color: tc.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(
          children: [
            // 시스템 상태 도트
            const _SystemDots(),
            const Spacer(),
            // FX 환율
            const _FxRateIndicator(),
            AppSpacing.hGapXl,
            // 마켓 시간 표시
            const _MarketHoursIndicator(),
            AppSpacing.hGapXl,
            // 현재 시각
            const _CurrentTime(),
          ],
        ),
      ),
    );
  }
}

class _SystemDots extends StatelessWidget {
  const _SystemDots();

  @override
  Widget build(BuildContext context) {
    return Consumer<DashboardProvider>(
      builder: (context, provider, _) {
        final status = provider.systemStatus;
        if (status == null) {
          return Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              _StatusDot(label: 'SYS', online: false),
            ],
          );
        }

        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _StatusDot(label: 'AI', online: status.claude),
            AppSpacing.hGapMd,
            _StatusDot(label: 'KIS', online: status.kis),
            AppSpacing.hGapMd,
            _StatusDot(label: 'DB', online: status.database),
            AppSpacing.hGapMd,
            _StatusDot(label: 'RDB', online: status.redis),
          ],
        );
      },
    );
  }
}

class _StatusDot extends StatelessWidget {
  final String label;
  final bool online;

  const _StatusDot({required this.label, required this.online});

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (online)
          PulsingDot(color: tc.profit, size: 7)
        else
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(
              color: tc.loss,
              shape: BoxShape.circle,
            ),
          ),
        const SizedBox(width: 4),
        Text(
          label,
          style: AppTypography.bodySmall.copyWith(fontSize: 10),
        ),
      ],
    );
  }
}

class _FxRateIndicator extends StatelessWidget {
  const _FxRateIndicator();

  @override
  Widget build(BuildContext context) {
    return Consumer<TaxFxProvider>(
      builder: (context, provider, _) {
        final fx = provider.fxStatus;
        if (fx == null) {
          return Text(
            'USD/KRW --',
            style: AppTypography.bodySmall.copyWith(fontSize: 11),
          );
        }

        final isUp = fx.dailyChangePct >= 0;
        final fmt = NumberFormat('#,##0.00');
        final tc = context.tc;
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'USD/KRW ${fmt.format(fx.usdKrwRate)}',
              style: AppTypography.numberSmall.copyWith(fontSize: 11),
            ),
            AppSpacing.hGapXs,
            Icon(
              isUp ? Icons.arrow_drop_up : Icons.arrow_drop_down,
              size: 14,
              color: isUp ? tc.profit : tc.loss,
            ),
          ],
        );
      },
    );
  }
}

class _MarketHoursIndicator extends StatelessWidget {
  const _MarketHoursIndicator();

  bool get _isMarketHours {
    // 미국 동부 시간 23:00 KST = 09:00 ET, 06:30 KST = 16:30 ET
    final now = DateTime.now().toUtc();
    // UTC +9 (KST) 기준 23:00~06:30
    final kstHour = (now.hour + 9) % 24;
    final kstMinute = now.minute;
    final totalKstMinutes = kstHour * 60 + kstMinute;
    // 23:00 = 1380분, 06:30 = 390분
    return totalKstMinutes >= 1380 || totalKstMinutes <= 390;
  }

  @override
  Widget build(BuildContext context) {
    final isOpen = _isMarketHours;
    final locale = context.watch<LocaleProvider>();
    final tc = context.tc;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: BoxDecoration(
            color: isOpen ? tc.profit : tc.textTertiary,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 4),
        Text(
          isOpen ? locale.t('market_open') : locale.t('market_closed'),
          style: AppTypography.bodySmall.copyWith(
            fontSize: 10,
            color: isOpen ? tc.profit : tc.textTertiary,
          ),
        ),
      ],
    );
  }
}

class _CurrentTime extends StatefulWidget {
  const _CurrentTime();

  @override
  State<_CurrentTime> createState() => _CurrentTimeState();
}

class _CurrentTimeState extends State<_CurrentTime> {
  late String _timeStr;

  @override
  void initState() {
    super.initState();
    _updateTime();
    // 1초마다 시간 업데이트
    Future.doWhile(() async {
      await Future.delayed(const Duration(seconds: 1));
      if (mounted) {
        setState(_updateTime);
        return true;
      }
      return false;
    });
  }

  void _updateTime() {
    final now = DateTime.now();
    _timeStr = DateFormat('HH:mm:ss').format(now);
  }

  @override
  Widget build(BuildContext context) {
    return Text(
      _timeStr,
      style: AppTypography.numberSmall.copyWith(fontSize: 11),
    );
  }
}

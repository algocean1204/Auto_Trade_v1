// TradingColors ThemeExtension 단위 테스트이다.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ai_trading_dashboard/theme/trading_colors.dart';

void main() {
  group('TradingColors.dark', () {
    test('background 색상이 올바른 값이다', () {
      expect(TradingColors.dark.background, const Color(0xFF06080F));
    });

    test('primary 색상이 올바른 값이다', () {
      expect(TradingColors.dark.primary, const Color(0xFF3B82F6));
    });

    test('profit 색상이 올바른 값이다', () {
      expect(TradingColors.dark.profit, const Color(0xFF10B981));
    });

    test('loss 색상이 올바른 값이다', () {
      expect(TradingColors.dark.loss, const Color(0xFFEF4444));
    });

    test('warning 색상이 올바른 값이다', () {
      expect(TradingColors.dark.warning, const Color(0xFFF59E0B));
    });

    test('surface 색상이 올바른 값이다', () {
      expect(TradingColors.dark.surface, const Color(0xFF0F1420));
    });

    test('textPrimary 색상이 올바른 값이다', () {
      expect(TradingColors.dark.textPrimary, const Color(0xF2FFFFFF));
    });
  });

  group('TradingColors.light', () {
    test('background 색상이 올바른 값이다', () {
      expect(TradingColors.light.background, const Color(0xFFF5F7FA));
    });

    test('primary 색상이 올바른 값이다', () {
      expect(TradingColors.light.primary, const Color(0xFF2563EB));
    });

    test('profit 색상이 올바른 값이다', () {
      expect(TradingColors.light.profit, const Color(0xFF059669));
    });

    test('loss 색상이 올바른 값이다', () {
      expect(TradingColors.light.loss, const Color(0xFFDC2626));
    });

    test('surface 색상이 올바른 값이다 (흰색)', () {
      expect(TradingColors.light.surface, const Color(0xFFFFFFFF));
    });

    test('textPrimary 색상이 올바른 값이다', () {
      expect(TradingColors.light.textPrimary, const Color(0xF20F172A));
    });
  });

  group('TradingColors.lerp', () {
    test('t=0이면 시작 값을 반환한다', () {
      final result = TradingColors.dark.lerp(TradingColors.light, 0);
      expect(result.background, TradingColors.dark.background);
      expect(result.primary, TradingColors.dark.primary);
    });

    test('t=1이면 끝 값을 반환한다', () {
      final result = TradingColors.dark.lerp(TradingColors.light, 1);
      expect(result.background, TradingColors.light.background);
      expect(result.primary, TradingColors.light.primary);
    });

    test('t=0.5이면 중간 값을 반환한다', () {
      final result = TradingColors.dark.lerp(TradingColors.light, 0.5);

      // 중간 보간 값이 dark도 light도 아닌지 확인한다.
      expect(result.background, isNot(TradingColors.dark.background));
      expect(result.background, isNot(TradingColors.light.background));
    });

    test('other가 null이면 자기 자신을 반환한다', () {
      final result = TradingColors.dark.lerp(null, 0.5);
      expect(result.background, TradingColors.dark.background);
      expect(result.primary, TradingColors.dark.primary);
    });
  });

  group('TradingColors.copyWith', () {
    test('인자 없이 호출하면 동일한 값을 복사한다', () {
      final copy = TradingColors.dark.copyWith();
      expect(copy.background, TradingColors.dark.background);
      expect(copy.primary, TradingColors.dark.primary);
      expect(copy.profit, TradingColors.dark.profit);
      expect(copy.loss, TradingColors.dark.loss);
      expect(copy.textPrimary, TradingColors.dark.textPrimary);
    });

    test('특정 필드만 오버라이드한다', () {
      final copy = TradingColors.dark.copyWith(
        primary: Colors.red,
        profit: Colors.blue,
      );
      expect(copy.primary, Colors.red);
      expect(copy.profit, Colors.blue);
      // 변경하지 않은 필드는 원래 값을 유지한다.
      expect(copy.background, TradingColors.dark.background);
      expect(copy.loss, TradingColors.dark.loss);
    });
  });

  group('TradingColors helper getters', () {
    test('pnlColor - 양수이면 profit, 음수이면 loss를 반환한다', () {
      expect(TradingColors.dark.pnlColor(1.0), TradingColors.dark.profit);
      expect(TradingColors.dark.pnlColor(-1.0), TradingColors.dark.loss);
      expect(TradingColors.dark.pnlColor(0.0), TradingColors.dark.profit);
    });

    test('pnlColorLight - 양수이면 profitLight, 음수이면 lossLight를 반환한다', () {
      expect(TradingColors.dark.pnlColorLight(1.0), TradingColors.dark.profitLight);
      expect(TradingColors.dark.pnlColorLight(-1.0), TradingColors.dark.lossLight);
    });

    test('pnlBg - 양수이면 profitBg, 음수이면 lossBg를 반환한다', () {
      expect(TradingColors.dark.pnlBg(1.0), TradingColors.dark.profitBg);
      expect(TradingColors.dark.pnlBg(-1.0), TradingColors.dark.lossBg);
    });

    test('severityColor - 심각도에 따른 색상을 반환한다', () {
      expect(TradingColors.dark.severityColor('critical'), TradingColors.dark.loss);
      expect(TradingColors.dark.severityColor('warning'), TradingColors.dark.warning);
      expect(TradingColors.dark.severityColor('info'), TradingColors.dark.info);
      expect(TradingColors.dark.severityColor('unknown'), TradingColors.dark.textTertiary);
    });

    test('profitBg - profit 색상의 12% opacity이다', () {
      final bg = TradingColors.dark.profitBg;
      expect(bg, isNotNull);
      // 12% opacity는 약 0.12 * 255 = ~31
      expect(bg.alpha, closeTo(31, 1));
    });
  });
}

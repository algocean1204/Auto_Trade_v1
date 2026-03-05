// ThemeProvider 단위 테스트이다.
// SharedPreferences 호출이 실패해도 상태 변경 자체는 정상 동작하는지 확인한다.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ai_trading_dashboard/providers/theme_provider.dart';

void main() {
  group('ThemeProvider', () {
    setUp(() {
      // SharedPreferences 테스트 모드 설정 (빈 초기값)
      SharedPreferences.setMockInitialValues({});
    });

    test('초기 테마 모드는 dark이다', () {
      final provider = ThemeProvider();
      expect(provider.themeMode, ThemeMode.dark);
      expect(provider.isDark, isTrue);
    });

    test('toggleTheme - dark에서 light로 전환한다', () async {
      final provider = ThemeProvider();
      expect(provider.isDark, isTrue);

      await provider.toggleTheme();

      expect(provider.themeMode, ThemeMode.light);
      expect(provider.isDark, isFalse);
    });

    test('toggleTheme - light에서 dark로 다시 전환한다', () async {
      final provider = ThemeProvider();

      // dark -> light
      await provider.toggleTheme();
      expect(provider.isDark, isFalse);

      // light -> dark
      await provider.toggleTheme();
      expect(provider.isDark, isTrue);
      expect(provider.themeMode, ThemeMode.dark);
    });

    test('setTheme - 특정 테마 모드를 직접 설정한다', () async {
      final provider = ThemeProvider();

      await provider.setTheme(ThemeMode.light);
      expect(provider.themeMode, ThemeMode.light);

      await provider.setTheme(ThemeMode.dark);
      expect(provider.themeMode, ThemeMode.dark);
    });

    test('setTheme - 동일한 모드 설정 시 변경하지 않는다', () async {
      final provider = ThemeProvider();
      // 초기값은 dark이다.

      int notifyCount = 0;
      provider.addListener(() => notifyCount++);

      // 이미 dark인 상태에서 dark를 설정하면 notifyListeners가 호출되지 않아야 한다.
      await provider.setTheme(ThemeMode.dark);
      expect(notifyCount, 0);
    });

    test('toggleTheme 호출 시 notifyListeners가 호출된다', () async {
      final provider = ThemeProvider();

      // _loadTheme()의 비동기 notifyListeners 호출을 대기한다.
      await Future.delayed(const Duration(milliseconds: 50));

      int notifyCount = 0;
      provider.addListener(() => notifyCount++);

      await provider.toggleTheme();
      expect(notifyCount, 1);
    });

    test('SharedPreferences에서 저장된 테마를 불러온다', () async {
      SharedPreferences.setMockInitialValues({'is_dark_mode': false});

      final provider = ThemeProvider();

      // _loadTheme가 비동기로 실행되므로 잠시 대기한다.
      await Future.delayed(const Duration(milliseconds: 100));

      expect(provider.themeMode, ThemeMode.light);
      expect(provider.isDark, isFalse);
    });
  });
}

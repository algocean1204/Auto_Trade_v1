// AppStrings 로컬라이제이션 테스트이다.
// 모든 키가 두 로케일(ko, en)에 존재하는지, t() 함수의 반환값을 검증한다.

import 'package:flutter_test/flutter_test.dart';

import 'package:ai_trading_dashboard/l10n/app_strings.dart';
import 'package:ai_trading_dashboard/providers/locale_provider.dart';

void main() {
  group('AppStrings.get - 기본 동작', () {
    test('한국어 키가 올바른 값을 반환한다', () {
      expect(AppStrings.get('app_title', 'ko'), 'AI 트레이딩 대시보드');
    });

    test('영어 키가 올바른 값을 반환한다', () {
      expect(AppStrings.get('app_title', 'en'), 'AI Trading Dashboard');
    });

    test('존재하지 않는 키는 키 자체를 반환한다', () {
      expect(AppStrings.get('nonexistent_key', 'ko'), 'nonexistent_key');
      expect(AppStrings.get('nonexistent_key', 'en'), 'nonexistent_key');
    });

    test('알 수 없는 로케일은 영어 fallback을 사용한다', () {
      expect(AppStrings.get('app_title', 'fr'), 'AI Trading Dashboard');
    });
  });

  group('AppStrings - 네비게이션 키 일관성', () {
    final navKeys = [
      'nav_overview',
      'nav_trading',
      'nav_risk',
      'nav_analytics',
      'nav_rsi',
      'nav_stock_analysis',
      'nav_reports',
      'nav_trade_reasoning',
      'nav_news',
      'nav_universe',
      'nav_agents',
      'nav_principles',
      'nav_settings',
    ];

    test('모든 네비게이션 키가 한국어에 존재한다', () {
      for (final key in navKeys) {
        final value = AppStrings.get(key, 'ko');
        expect(value, isNot(equals(key)),
            reason: 'ko 로케일에 "$key" 키가 없다');
      }
    });

    test('모든 네비게이션 키가 영어에 존재한다', () {
      for (final key in navKeys) {
        final value = AppStrings.get(key, 'en');
        expect(value, isNot(equals(key)),
            reason: 'en 로케일에 "$key" 키가 없다');
      }
    });
  });

  group('AppStrings - 사이드바 키 일관성', () {
    final sidebarKeys = [
      'sidebar_title',
      'sidebar_subtitle',
      'sidebar_footer',
    ];

    test('모든 사이드바 키가 두 로케일에 존재한다', () {
      for (final key in sidebarKeys) {
        final koValue = AppStrings.get(key, 'ko');
        final enValue = AppStrings.get(key, 'en');
        expect(koValue, isNot(equals(key)),
            reason: 'ko에 "$key" 누락');
        expect(enValue, isNot(equals(key)),
            reason: 'en에 "$key" 누락');
      }
    });
  });

  group('AppStrings - 에러/상태 키 일관성', () {
    final errorKeys = [
      'connection_error',
      'retry',
      'no_data_available',
      'connect_to_system',
      'failed',
    ];

    test('모든 에러 키가 두 로케일에 존재한다', () {
      for (final key in errorKeys) {
        final koValue = AppStrings.get(key, 'ko');
        final enValue = AppStrings.get(key, 'en');
        expect(koValue, isNot(equals(key)),
            reason: 'ko에 "$key" 누락');
        expect(enValue, isNot(equals(key)),
            reason: 'en에 "$key" 누락');
      }
    });
  });

  group('AppStrings - 테마 키 일관성', () {
    test('테마 관련 키가 두 로케일에 존재한다', () {
      expect(AppStrings.get('theme_dark', 'ko'), '다크 모드');
      expect(AppStrings.get('theme_dark', 'en'), 'Dark Mode');
      expect(AppStrings.get('theme_light', 'ko'), '라이트 모드');
      expect(AppStrings.get('theme_light', 'en'), 'Light Mode');
    });
  });

  group('AppStrings - 종합 키 대칭성', () {
    // 대표적인 키 그룹들을 검증한다.
    final importantKeys = [
      'app_title',
      'total_portfolio',
      'today_pnl',
      'cash',
      'positions',
      'system_status',
      'online',
      'offline',
      'trading',
      'risk_safety',
      'analytics',
      'settings',
      'emergency_stop',
      'cancel',
      'confirm',
      'save',
      'delete',
      'refresh',
      'alerts',
      'language',
    ];

    test('중요 키들이 ko와 en 모두에 존재한다', () {
      for (final key in importantKeys) {
        final koValue = AppStrings.get(key, 'ko');
        final enValue = AppStrings.get(key, 'en');
        expect(koValue, isNot(equals(key)),
            reason: 'ko에 "$key" 누락');
        expect(enValue, isNot(equals(key)),
            reason: 'en에 "$key" 누락');
      }
    });

    test('ko와 en 값이 서로 다르다 (번역됨을 확인)', () {
      // sidebar_footer는 동일할 수 있으므로 제외한다.
      final keysToCheck = ['app_title', 'total_portfolio', 'settings', 'cancel'];
      for (final key in keysToCheck) {
        final koValue = AppStrings.get(key, 'ko');
        final enValue = AppStrings.get(key, 'en');
        expect(koValue, isNot(equals(enValue)),
            reason: '"$key"의 ko와 en 값이 동일하다');
      }
    });
  });

  group('LocaleProvider.t() 통합 테스트', () {
    test('한국어 모드에서 t()가 올바른 값을 반환한다', () {
      final provider = LocaleProvider();
      expect(provider.locale, 'ko');
      expect(provider.t('app_title'), 'AI 트레이딩 대시보드');
      expect(provider.t('nav_overview'), '개요');
    });

    test('영어 모드에서 t()가 올바른 값을 반환한다', () {
      final provider = LocaleProvider();
      provider.setLocale('en');
      expect(provider.t('app_title'), 'AI Trading Dashboard');
      expect(provider.t('nav_overview'), 'Overview');
    });

    test('toggleLocale 후 t()가 전환된 값을 반환한다', () {
      final provider = LocaleProvider();
      expect(provider.t('save'), '저장');

      provider.toggleLocale();
      expect(provider.t('save'), 'Save');

      provider.toggleLocale();
      expect(provider.t('save'), '저장');
    });

    test('존재하지 않는 키에 대해 키 자체를 반환한다', () {
      final provider = LocaleProvider();
      expect(provider.t('this_does_not_exist'), 'this_does_not_exist');
    });
  });

  group('AppStrings - 종목 분석 키', () {
    final analysisKeys = [
      'nav_stock_analysis',
      'stock_analysis_title',
      'current_situation',
      'predictions',
      'key_factors',
      'risk_factors',
      'recommendation',
      'analyzing',
    ];

    test('종목 분석 키들이 두 로케일에 존재한다', () {
      for (final key in analysisKeys) {
        final koValue = AppStrings.get(key, 'ko');
        final enValue = AppStrings.get(key, 'en');
        expect(koValue, isNot(equals(key)),
            reason: 'ko에 "$key" 누락');
        expect(enValue, isNot(equals(key)),
            reason: 'en에 "$key" 누락');
      }
    });
  });

  group('AppStrings - 매크로/경제지표 키', () {
    final macroKeys = [
      'fear_greed_index',
      'fed_rate',
      'cpi',
      'unemployment',
      'economic_calendar',
      'rate_outlook',
    ];

    test('매크로 키들이 두 로케일에 존재한다', () {
      for (final key in macroKeys) {
        final koValue = AppStrings.get(key, 'ko');
        final enValue = AppStrings.get(key, 'en');
        expect(koValue, isNot(equals(key)),
            reason: 'ko에 "$key" 누락');
        expect(enValue, isNot(equals(key)),
            reason: 'en에 "$key" 누락');
      }
    });
  });
}

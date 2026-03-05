import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 앱 테마(다크/라이트) 상태를 관리한다.
/// SharedPreferences를 통해 사용자의 선택을 영구 저장한다.
class ThemeProvider extends ChangeNotifier {
  ThemeMode _themeMode = ThemeMode.dark;

  ThemeMode get themeMode => _themeMode;

  /// 현재 테마가 다크인지 여부를 반환한다.
  bool get isDark => _themeMode == ThemeMode.dark;

  ThemeProvider() {
    _loadTheme();
  }

  /// 저장된 테마 설정을 불러온다.
  Future<void> _loadTheme() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final isDark = prefs.getBool('is_dark_mode') ?? true;
      _themeMode = isDark ? ThemeMode.dark : ThemeMode.light;
      notifyListeners();
    } catch (_) {
      // 기본값 유지 (다크 모드)
    }
  }

  /// 다크/라이트 모드를 토글하고 설정을 저장한다.
  Future<void> toggleTheme() async {
    _themeMode = isDark ? ThemeMode.light : ThemeMode.dark;
    notifyListeners();
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool('is_dark_mode', _themeMode == ThemeMode.dark);
    } catch (_) {
      // 저장 실패 시 상태는 이미 변경되어 있으므로 무시한다
    }
  }

  /// 특정 테마 모드를 직접 설정한다.
  Future<void> setTheme(ThemeMode mode) async {
    if (_themeMode == mode) return;
    _themeMode = mode;
    notifyListeners();
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool('is_dark_mode', mode == ThemeMode.dark);
    } catch (_) {
      // 저장 실패 무시
    }
  }
}

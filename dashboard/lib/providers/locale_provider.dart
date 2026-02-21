import 'package:flutter/material.dart';
import '../l10n/app_strings.dart';

/// 앱 로케일(언어)을 관리하는 Provider이다. 기본값은 한국어('ko')이다.
class LocaleProvider with ChangeNotifier {
  String _locale = 'ko'; // 기본 한국어

  String get locale => _locale;
  bool get isKorean => _locale == 'ko';

  /// 특정 로케일로 변경한다.
  void setLocale(String locale) {
    if (_locale != locale) {
      _locale = locale;
      notifyListeners();
    }
  }

  /// 한국어/영어를 토글한다.
  void toggleLocale() {
    _locale = _locale == 'ko' ? 'en' : 'ko';
    notifyListeners();
  }

  /// 키에 해당하는 현재 로케일 문자열을 반환하는 단축 메서드이다.
  String t(String key) => AppStrings.get(key, _locale);
}

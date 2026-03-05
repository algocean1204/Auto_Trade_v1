import 'package:flutter/material.dart';

/// 투자 모드(모의/실전)를 나타내는 열거형이다.
enum TradingMode { virtual, real }

/// 모의투자와 실전투자 모드를 관리하는 Provider이다.
/// 모드 전환 시 모든 구독 위젯에 알림을 보내어 데이터가 재로드된다.
class TradingModeProvider extends ChangeNotifier {
  TradingMode _mode = TradingMode.virtual;

  /// 현재 활성 투자 모드이다.
  TradingMode get mode => _mode;

  /// API 요청에 사용할 모드 문자열이다 ('virtual' 또는 'real').
  String get modeString => _mode == TradingMode.virtual ? 'virtual' : 'real';

  /// 현재 모드가 모의투자인지 여부이다.
  bool get isVirtual => _mode == TradingMode.virtual;

  /// 현재 모드가 실전투자인지 여부이다.
  bool get isReal => _mode == TradingMode.real;

  /// 지정한 모드로 전환한다. 이미 같은 모드라면 아무것도 하지 않는다.
  void switchMode(TradingMode mode) {
    if (_mode != mode) {
      _mode = mode;
      notifyListeners();
    }
  }

  /// 현재 모드를 반전한다 (virtual <-> real).
  void toggle() {
    _mode = _mode == TradingMode.virtual ? TradingMode.real : TradingMode.virtual;
    notifyListeners();
  }
}

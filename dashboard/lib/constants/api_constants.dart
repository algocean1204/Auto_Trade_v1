/// API 관련 타임아웃 상수를 정의한다.
///
/// api_service.dart 에서 참조하며, 동일한 의미의 값이
/// 여러 곳에 중복될 때만 이 파일에 추가한다.
class ApiConstants {
  ApiConstants._();

  /// 일반 HTTP 요청 타임아웃 (api_service.dart _timeout 참조).
  static const defaultTimeout = Duration(seconds: 15);

  /// AI 분석·EOD 시퀀스처럼 시간이 오래 걸리는 요청의 타임아웃.
  /// getStockAnalysis, stopTrading 에서 공통으로 사용한다.
  static const longTimeout = Duration(seconds: 120);
}

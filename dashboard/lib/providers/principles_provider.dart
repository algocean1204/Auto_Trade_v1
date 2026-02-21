import 'package:flutter/material.dart';
import '../models/principles_models.dart';
import '../services/api_service.dart';

/// 매매 원칙 상태 관리 프로바이더이다.
class PrinciplesProvider with ChangeNotifier {
  final ApiService _api;

  TradingPrinciples? _data;
  bool _isLoading = false;
  String? _error;

  /// 현재 선택된 카테고리 필터 ('all', 'survival', 'risk', 'strategy', 'execution')
  String _selectedCategory = 'all';

  PrinciplesProvider(this._api);

  TradingPrinciples? get data => _data;
  bool get isLoading => _isLoading;
  String? get error => _error;
  String get selectedCategory => _selectedCategory;

  List<TradingPrinciple> get principles => _data?.principles ?? [];
  String get corePrinciple => _data?.corePrinciple ?? '';

  /// 카테고리 필터가 적용된 원칙 목록을 반환한다.
  List<TradingPrinciple> get filteredPrinciples {
    final all = principles;
    if (_selectedCategory == 'all') return all;
    return all.where((p) => p.category == _selectedCategory).toList();
  }

  /// 카테고리 필터를 설정한다.
  void setCategory(String category) {
    if (_selectedCategory != category) {
      _selectedCategory = category;
      notifyListeners();
    }
  }

  /// 매매 원칙 데이터를 로드한다.
  Future<void> load() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _data = await _api.getPrinciples();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 새 원칙을 추가한다.
  Future<void> addPrinciple(
      String category, String title, String content) async {
    try {
      await _api.addPrinciple(category, title, content);
      await load();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 기존 원칙을 수정한다.
  Future<void> updatePrinciple(
    String id, {
    String? title,
    String? content,
    bool? enabled,
  }) async {
    final updates = <String, dynamic>{};
    if (title != null) updates['title'] = title;
    if (content != null) updates['content'] = content;
    if (enabled != null) updates['enabled'] = enabled;

    try {
      await _api.updatePrinciple(id, updates);
      await load();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 원칙을 삭제한다.
  Future<void> deletePrinciple(String id) async {
    try {
      await _api.deletePrinciple(id);
      await load();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 핵심 원칙(슬로건)을 수정한다.
  Future<void> updateCorePrinciple(String text) async {
    try {
      await _api.updateCorePrinciple(text);
      await load();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }

  /// 데이터를 새로고침한다.
  Future<void> refresh() async {
    _data = null;
    await load();
  }
}

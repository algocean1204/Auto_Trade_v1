import 'package:flutter/material.dart';

import '../../theme/app_spacing.dart';
import '../../theme/trading_colors.dart';

/// API 키 입력 필드 위젯이다.
/// 비밀번호 마스킹 토글, 선택적 검증 버튼, 검증 결과 아이콘을 제공한다.
class ApiKeyField extends StatefulWidget {
  final String label;
  final String? hintText;
  final String? value;
  final ValueChanged<String> onChanged;
  final VoidCallback? onValidate;
  final bool isValidating;
  final bool? isValid; // null=미검증, true=성공, false=실패
  final bool obscure;

  const ApiKeyField({
    super.key,
    required this.label,
    this.hintText,
    this.value,
    required this.onChanged,
    this.onValidate,
    this.isValidating = false,
    this.isValid,
    this.obscure = true,
  });

  @override
  State<ApiKeyField> createState() => _ApiKeyFieldState();
}

class _ApiKeyFieldState extends State<ApiKeyField> {
  late bool _obscured;
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _obscured = widget.obscure;
    _controller = TextEditingController(text: widget.value);
  }

  @override
  void didUpdateWidget(covariant ApiKeyField oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 부모에서 value가 변경되었고 사용자가 직접 입력한 게 아니면 controller를 갱신한다
    if (widget.value != oldWidget.value && widget.value != _controller.text) {
      _controller.text = widget.value ?? '';
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tc = context.tc;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextFormField(
          controller: _controller,
          obscureText: _obscured,
          onChanged: widget.onChanged,
          decoration: InputDecoration(
            labelText: widget.label,
            hintText: widget.hintText,
            suffixIcon: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                // 마스킹 토글 아이콘
                IconButton(
                  icon: Icon(
                    _obscured ? Icons.visibility_off : Icons.visibility,
                    size: 20,
                    color: tc.textTertiary,
                  ),
                  onPressed: () => setState(() => _obscured = !_obscured),
                  tooltip: _obscured ? '보기' : '숨기기',
                ),
                // 검증 결과 아이콘
                if (widget.isValid != null)
                  Icon(
                    widget.isValid! ? Icons.check_circle : Icons.error,
                    size: 20,
                    color: widget.isValid! ? tc.profit : tc.loss,
                  ),
              ],
            ),
          ),
        ),
        if (widget.onValidate != null) ...[
          AppSpacing.vGapSm,
          SizedBox(
            height: 36,
            child: ElevatedButton(
              onPressed: widget.isValidating ? null : widget.onValidate,
              child: widget.isValidating
                  ? const SizedBox(
                      width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('검증'),
            ),
          ),
        ],
      ],
    );
  }
}

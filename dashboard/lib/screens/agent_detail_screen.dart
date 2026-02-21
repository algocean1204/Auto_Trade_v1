import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import '../models/agent_models.dart';
import '../providers/agent_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';

/// 에이전트 상세 화면이다.
/// 에이전트의 MD 콘텐츠를 보기/편집 모드로 표시한다.
class AgentDetailScreen extends StatefulWidget {
  final AgentInfo agent;
  final AgentTeam team;

  const AgentDetailScreen({
    super.key,
    required this.agent,
    required this.team,
  });

  @override
  State<AgentDetailScreen> createState() => _AgentDetailScreenState();
}

class _AgentDetailScreenState extends State<AgentDetailScreen> {
  bool _editMode = false;
  String? _loadedContent;
  late TextEditingController _editController;
  bool _hasUnsavedChanges = false;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _editController = TextEditingController();
    _loadContent();
  }

  @override
  void dispose() {
    _editController.dispose();
    super.dispose();
  }

  Future<void> _loadContent() async {
    final provider = context.read<AgentProvider>();
    // 캐시 확인
    final cached = provider.getCachedMd(widget.agent.id);
    if (cached != null) {
      setState(() {
        _loadedContent = cached;
        _editController.text = cached;
      });
      return;
    }
    // API에서 로드
    final content = await provider.loadAgentMd(widget.agent.id);
    if (mounted) {
      setState(() {
        _loadedContent = content ?? _buildDefaultMdContent();
        _editController.text = _loadedContent ?? '';
      });
    }
  }

  /// API에서 콘텐츠를 가져오지 못할 때 사용할 기본 MD 콘텐츠이다.
  String _buildDefaultMdContent() {
    return '''# ${widget.agent.name}

## 개요

**팀**: ${widget.team.type.labelKey}
**상태**: ${widget.agent.isActive ? '활성' : '비활성'}

## 설명

${widget.agent.description}

## 역할

이 에이전트는 Trading AI System V2의 ${widget.team.type.labelKey}의 일부로 동작한다.

## 주요 기능

- 기능 1
- 기능 2
- 기능 3

## 인터페이스

```python
# 예시 코드
class ${widget.agent.name}:
    async def run(self) -> None:
        pass
```

## 참고

자세한 구현은 `src/` 디렉토리를 참조한다.
''';
  }

  Future<void> _save() async {
    if (_isSaving) return;
    setState(() => _isSaving = true);

    final content = _editController.text;
    final provider = context.read<AgentProvider>();
    final success = await provider.saveAgentMd(widget.agent.id, content);

    if (mounted) {
      setState(() {
        _isSaving = false;
        if (success) {
          _loadedContent = content;
          _hasUnsavedChanges = false;
          _editMode = false;
        }
      });

      final locale = context.read<LocaleProvider>();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            success
                ? locale.t('save_success')
                : locale.t('save_agent_failed'),
          ),
          backgroundColor: success ? context.tc.profit : context.tc.loss,
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.borderRadiusMd,
          ),
          margin: const EdgeInsets.all(16),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  Future<bool> _onWillPop() async {
    if (!_hasUnsavedChanges) return true;
    final locale = context.read<LocaleProvider>();
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: context.tc.surfaceElevated,
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          side: BorderSide(
            color: context.tc.surfaceBorder.withValues(alpha: 0.5),
          ),
        ),
        title: Text(
          locale.t('unsaved_changes'),
          style: AppTypography.labelLarge,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(
              locale.t('cancel_edit'),
              style: AppTypography.labelMedium.copyWith(
                color: context.tc.textSecondary,
              ),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(
              locale.t('discard_changes'),
              style: AppTypography.labelMedium.copyWith(
                color: context.tc.loss,
              ),
            ),
          ),
        ],
      ),
    );
    return result ?? false;
  }

  void _toggleEditMode() {
    if (_editMode && _hasUnsavedChanges) {
      // 편집 취소 시 변경사항을 버린다
      setState(() {
        _editController.text = _loadedContent ?? '';
        _hasUnsavedChanges = false;
        _editMode = false;
      });
    } else {
      setState(() {
        _editMode = !_editMode;
      });
    }
  }

  Color get _teamColor {
    final tc = context.tc;
    switch (widget.team.type) {
      case AgentTeamType.crawling:
        return tc.chart1;
      case AgentTeamType.analysis:
        return tc.chart4;
      case AgentTeamType.decision:
        return tc.chart3;
      case AgentTeamType.execution:
        return tc.profit;
      case AgentTeamType.safety:
        return tc.warning;
      case AgentTeamType.monitoring:
        return tc.chart2;
    }
  }

  @override
  Widget build(BuildContext context) {
    final locale = context.watch<LocaleProvider>();

    return PopScope(
      canPop: !_hasUnsavedChanges,
      onPopInvokedWithResult: (didPop, result) async {
        if (!didPop && _hasUnsavedChanges) {
          final canLeave = await _onWillPop();
          if (canLeave && context.mounted) {
            Navigator.of(context).pop();
          }
        }
      },
      child: Scaffold(
        backgroundColor: context.tc.background,
        appBar: _buildAppBar(context, locale),
        body: _buildBody(locale),
      ),
    );
  }

  PreferredSizeWidget _buildAppBar(
      BuildContext context, LocaleProvider locale) {
    return AppBar(
      backgroundColor: context.tc.surface,
      elevation: 0,
      toolbarHeight: 56,
      leading: IconButton(
        icon: Icon(
          Icons.arrow_back_rounded,
          color: context.tc.textSecondary,
          size: 20,
        ),
        onPressed: () async {
          if (_hasUnsavedChanges) {
            final canLeave = await _onWillPop();
            if (canLeave && context.mounted) {
              Navigator.of(context).pop();
            }
          } else {
            Navigator.of(context).pop();
          }
        },
      ),
      title: Row(
        children: [
          // 팀 이모지
          Text(
            widget.team.type.emoji,
            style: const TextStyle(fontSize: 18),
          ),
          AppSpacing.hGapSm,
          // 에이전트 이름 + 팀 이름
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.agent.name,
                  style: AppTypography.labelLarge.copyWith(fontSize: 15),
                ),
                Text(
                  locale.t(widget.team.type.labelKey),
                  style: AppTypography.bodySmall.copyWith(
                    fontSize: 11,
                    color: _teamColor,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      actions: [
        // 상태 뱃지
        Container(
          margin: const EdgeInsets.symmetric(vertical: 14, horizontal: 4),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
            color: widget.agent.isActive
                ? context.tc.profit.withValues(alpha: 0.15)
                : context.tc.textDisabled.withValues(alpha: 0.1),
            borderRadius: AppSpacing.borderRadiusFull,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 5,
                height: 5,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: widget.agent.isActive
                      ? context.tc.profit
                      : context.tc.textDisabled,
                ),
              ),
              const SizedBox(width: 4),
              Text(
                locale.t(
                    widget.agent.isActive ? 'agent_active' : 'agent_inactive'),
                style: AppTypography.bodySmall.copyWith(
                  fontSize: 10,
                  color: widget.agent.isActive
                      ? context.tc.profit
                      : context.tc.textDisabled,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        // 편집/취소 버튼
        if (_loadedContent != null)
          TextButton.icon(
            onPressed: _toggleEditMode,
            icon: Icon(
              _editMode
                  ? Icons.close_rounded
                  : Icons.edit_rounded,
              size: 16,
              color: _editMode
                  ? context.tc.textSecondary
                  : context.tc.primary,
            ),
            label: Text(
              _editMode
                  ? locale.t('cancel_edit')
                  : locale.t('edit_agent'),
              style: AppTypography.labelMedium.copyWith(
                color: _editMode
                    ? context.tc.textSecondary
                    : context.tc.primary,
                fontSize: 12,
              ),
            ),
          ),
        // 저장 버튼 (편집 모드에서만 표시)
        if (_editMode)
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: TextButton.icon(
              onPressed: _isSaving ? null : _save,
              style: TextButton.styleFrom(
                backgroundColor: context.tc.primary.withValues(alpha: 0.12),
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.borderRadiusMd,
                ),
                padding: const EdgeInsets.symmetric(
                    horizontal: 12, vertical: 6),
              ),
              icon: _isSaving
                  ? SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: context.tc.primary,
                      ),
                    )
                  : Icon(
                      Icons.save_rounded,
                      size: 16,
                      color: context.tc.primary,
                    ),
              label: Text(
                locale.t('save_agent'),
                style: AppTypography.labelMedium.copyWith(
                  color: context.tc.primary,
                  fontSize: 12,
                ),
              ),
            ),
          ),
        const SizedBox(width: 4),
      ],
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(1),
        child: Container(
          height: 1,
          color: context.tc.surfaceBorder.withValues(alpha: 0.2),
        ),
      ),
    );
  }

  Widget _buildBody(LocaleProvider locale) {
    return Consumer<AgentProvider>(
      builder: (context, provider, _) {
        // 로딩 상태
        if (provider.isMdLoading && _loadedContent == null) {
          return Center(
            child: CircularProgressIndicator(color: context.tc.primary),
          );
        }

        // 에러 상태
        if (provider.mdError != null && _loadedContent == null) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  Icons.error_outline_rounded,
                  size: 48,
                  color: context.tc.loss.withValues(alpha: 0.6),
                ),
                AppSpacing.vGapMd,
                Text(
                  locale.t('md_load_failed'),
                  style: AppTypography.bodyMedium,
                ),
                AppSpacing.vGapMd,
                TextButton(
                  onPressed: _loadContent,
                  child: Text(
                    locale.t('retry'),
                    style: AppTypography.labelMedium.copyWith(
                      color: context.tc.primary,
                    ),
                  ),
                ),
              ],
            ),
          );
        }

        final content = _loadedContent ?? locale.t('no_md_content');

        if (_editMode) {
          return _buildEditView(content, locale);
        } else {
          return _buildViewMode(content);
        }
      },
    );
  }

  /// 편집 모드 - 풀스크린 텍스트 에디터이다.
  Widget _buildEditView(String initialContent, LocaleProvider locale) {
    return Column(
      children: [
        // 편집 모드 배너
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          color: context.tc.primary.withValues(alpha: 0.08),
          child: Row(
            children: [
              Icon(
                Icons.edit_note_rounded,
                size: 16,
                color: context.tc.primary.withValues(alpha: 0.8),
              ),
              AppSpacing.hGapSm,
              Text(
                locale.t('edit_mode'),
                style: AppTypography.bodySmall.copyWith(
                  color: context.tc.primary.withValues(alpha: 0.9),
                  fontSize: 12,
                ),
              ),
              const Spacer(),
              if (_hasUnsavedChanges)
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: context.tc.warning.withValues(alpha: 0.15),
                    borderRadius: AppSpacing.borderRadiusFull,
                  ),
                  child: Text(
                    '\u25CF',
                    style: TextStyle(
                      fontSize: 8,
                      color: context.tc.warning,
                    ),
                  ),
                ),
            ],
          ),
        ),
        // 텍스트 에디터
        Expanded(
          child: Container(
            color: context.tc.background,
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: TextField(
              controller: _editController,
              maxLines: null,
              expands: true,
              textAlignVertical: TextAlignVertical.top,
              style: GoogleFonts.jetBrainsMono(
                fontSize: 13,
                color: context.tc.textPrimary,
                height: 1.6,
              ),
              decoration: InputDecoration(
                border: InputBorder.none,
                hintText: '# ${widget.agent.name}\n\n...',
                hintStyle: GoogleFonts.jetBrainsMono(
                  fontSize: 13,
                  color: context.tc.textDisabled,
                ),
              ),
              onChanged: (value) {
                if (!_hasUnsavedChanges) {
                  setState(() => _hasUnsavedChanges = true);
                }
              },
            ),
          ),
        ),
      ],
    );
  }

  /// 보기 모드 - MD 파싱 후 스타일 적용하여 렌더링한다.
  Widget _buildViewMode(String content) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: _parseMarkdown(content),
      ),
    );
  }

  /// 마크다운 텍스트를 파싱하여 위젯 목록을 생성한다.
  List<Widget> _parseMarkdown(String content) {
    final lines = content.split('\n');
    final widgets = <Widget>[];
    final List<String> codeBuffer = [];
    bool inCodeBlock = false;
    String codeLang = '';

    for (int i = 0; i < lines.length; i++) {
      final line = lines[i];

      // 코드 블록 처리
      if (line.startsWith('```')) {
        if (inCodeBlock) {
          // 코드 블록 종료
          widgets.add(_buildCodeBlock(codeBuffer.join('\n'), codeLang));
          widgets.add(AppSpacing.vGapMd);
          codeBuffer.clear();
          inCodeBlock = false;
          codeLang = '';
        } else {
          // 코드 블록 시작
          inCodeBlock = true;
          codeLang = line.substring(3).trim();
        }
        continue;
      }

      if (inCodeBlock) {
        codeBuffer.add(line);
        continue;
      }

      // 빈 줄
      if (line.trim().isEmpty) {
        widgets.add(AppSpacing.vGapSm);
        continue;
      }

      // H1 헤더
      if (line.startsWith('# ')) {
        widgets.add(_buildH1(line.substring(2)));
        widgets.add(AppSpacing.vGapMd);
        continue;
      }

      // H2 헤더
      if (line.startsWith('## ')) {
        widgets.add(AppSpacing.vGapSm);
        widgets.add(_buildH2(line.substring(3)));
        widgets.add(AppSpacing.vGapSm);
        continue;
      }

      // H3 헤더
      if (line.startsWith('### ')) {
        widgets.add(_buildH3(line.substring(4)));
        widgets.add(AppSpacing.vGapXs);
        continue;
      }

      // 수평선
      if (line.trim() == '---' || line.trim() == '***') {
        widgets.add(_buildDivider());
        widgets.add(AppSpacing.vGapSm);
        continue;
      }

      // 불릿 목록
      if (line.startsWith('- ') || line.startsWith('* ')) {
        widgets.add(_buildBulletItem(line.substring(2)));
        continue;
      }

      // 번호 목록
      final numberedMatch = RegExp(r'^(\d+)\.\s(.+)').firstMatch(line);
      if (numberedMatch != null) {
        widgets.add(
            _buildNumberedItem(numberedMatch.group(1)!, numberedMatch.group(2)!));
        continue;
      }

      // 인용문
      if (line.startsWith('> ')) {
        widgets.add(_buildBlockquote(line.substring(2)));
        widgets.add(AppSpacing.vGapXs);
        continue;
      }

      // 일반 텍스트 (인라인 형식 처리 포함)
      widgets.add(_buildParagraph(line));
    }

    // 코드 블록이 닫히지 않은 경우 처리
    if (inCodeBlock && codeBuffer.isNotEmpty) {
      widgets.add(_buildCodeBlock(codeBuffer.join('\n'), codeLang));
    }

    return widgets;
  }

  Widget _buildH1(String text) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          text,
          style: AppTypography.displaySmall.copyWith(
            color: context.tc.textPrimary,
          ),
        ),
        const SizedBox(height: 8),
        Container(
          height: 2,
          width: double.infinity,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [
                _teamColor,
                _teamColor.withValues(alpha: 0),
              ],
            ),
            borderRadius: AppSpacing.borderRadiusFull,
          ),
        ),
      ],
    );
  }

  Widget _buildH2(String text) {
    return Row(
      children: [
        Container(
          width: 3,
          height: 18,
          decoration: BoxDecoration(
            color: _teamColor,
            borderRadius: AppSpacing.borderRadiusFull,
          ),
        ),
        AppSpacing.hGapSm,
        Expanded(
          child: Text(
            text,
            style: AppTypography.headlineMedium.copyWith(fontSize: 16),
          ),
        ),
      ],
    );
  }

  Widget _buildH3(String text) {
    return Text(
      text,
      style: AppTypography.labelLarge.copyWith(
        fontSize: 14,
        color: context.tc.textSecondary,
      ),
    );
  }

  Widget _buildDivider() {
    return Container(
      height: 1,
      color: context.tc.surfaceBorder.withValues(alpha: 0.4),
    );
  }

  Widget _buildBulletItem(String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(width: 8),
          Padding(
            padding: const EdgeInsets.only(top: 7),
            child: Container(
              width: 4,
              height: 4,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: _teamColor,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _buildInlineText(text),
          ),
        ],
      ),
    );
  }

  Widget _buildNumberedItem(String number, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(width: 8),
          Text(
            '$number.',
            style: AppTypography.bodyMedium.copyWith(
              color: _teamColor,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: _buildInlineText(text),
          ),
        ],
      ),
    );
  }

  Widget _buildBlockquote(String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        border: Border(
          left: BorderSide(
            color: _teamColor.withValues(alpha: 0.5),
            width: 3,
          ),
        ),
        color: _teamColor.withValues(alpha: 0.05),
      ),
      child: _buildInlineText(text),
    );
  }

  Widget _buildCodeBlock(String code, String lang) {
    return GlassCard(
      padding: EdgeInsets.zero,
      backgroundColor: context.tc.background.withValues(alpha: 0.8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (lang.isNotEmpty)
            Container(
              padding: const EdgeInsets.symmetric(
                  horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: _teamColor.withValues(alpha: 0.1),
                borderRadius: const BorderRadius.vertical(
                  top: Radius.circular(AppSpacing.radiusLg),
                ),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.code_rounded,
                    size: 12,
                    color: _teamColor,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    lang,
                    style: AppTypography.bodySmall.copyWith(
                      color: _teamColor,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.all(12),
            child: SelectableText(
              code,
              style: GoogleFonts.jetBrainsMono(
                fontSize: 12,
                color: context.tc.textSecondary,
                height: 1.6,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildParagraph(String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: _buildInlineText(text),
    );
  }

  /// 인라인 마크다운(굵기, 이탤릭, 인라인 코드, 볼드+이탤릭)을 파싱하여 RichText로 렌더링한다.
  Widget _buildInlineText(String text) {
    final spans = _parseInlineMarkdown(text);
    return RichText(
      text: TextSpan(children: spans),
    );
  }

  /// 인라인 마크다운 패턴을 파싱하여 InlineSpan 목록으로 변환한다.
  List<InlineSpan> _parseInlineMarkdown(String text) {
    final spans = <InlineSpan>[];
    final baseStyle = AppTypography.bodyMedium;

    // 인라인 패턴: 볼드+이탤릭(***), 볼드(**), 이탤릭(*), 인라인코드(`)
    final pattern = RegExp(
      r'\*\*\*(.+?)\*\*\*|'
      r'\*\*(.+?)\*\*|'
      r'\*(.+?)\*|'
      r'`(.+?)`|'
      r'\[(.+?)\]\((.+?)\)',
    );

    int lastEnd = 0;
    for (final match in pattern.allMatches(text)) {
      // 매치 이전 일반 텍스트
      if (match.start > lastEnd) {
        spans.add(TextSpan(
          text: text.substring(lastEnd, match.start),
          style: baseStyle,
        ));
      }

      if (match.group(1) != null) {
        // 볼드 + 이탤릭
        spans.add(TextSpan(
          text: match.group(1),
          style: baseStyle.copyWith(
            fontWeight: FontWeight.w700,
            fontStyle: FontStyle.italic,
            color: context.tc.textPrimary,
          ),
        ));
      } else if (match.group(2) != null) {
        // 볼드
        spans.add(TextSpan(
          text: match.group(2),
          style: baseStyle.copyWith(
            fontWeight: FontWeight.w700,
            color: context.tc.textPrimary,
          ),
        ));
      } else if (match.group(3) != null) {
        // 이탤릭
        spans.add(TextSpan(
          text: match.group(3),
          style: baseStyle.copyWith(
            fontStyle: FontStyle.italic,
            color: context.tc.textSecondary,
          ),
        ));
      } else if (match.group(4) != null) {
        // 인라인 코드
        spans.add(WidgetSpan(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
            decoration: BoxDecoration(
              color: _teamColor.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              match.group(4)!,
              style: GoogleFonts.jetBrainsMono(
                fontSize: 12,
                color: _teamColor,
                height: 1.4,
              ),
            ),
          ),
        ));
      } else if (match.group(5) != null && match.group(6) != null) {
        // 링크
        spans.add(TextSpan(
          text: match.group(5),
          style: baseStyle.copyWith(
            color: context.tc.primary,
            decoration: TextDecoration.underline,
            decorationColor: context.tc.primary.withValues(alpha: 0.5),
          ),
        ));
      }

      lastEnd = match.end;
    }

    // 남은 텍스트
    if (lastEnd < text.length) {
      spans.add(TextSpan(
        text: text.substring(lastEnd),
        style: baseStyle,
      ));
    }

    // 빈 경우 기본 텍스트
    if (spans.isEmpty) {
      spans.add(TextSpan(text: text, style: baseStyle));
    }

    return spans;
  }
}

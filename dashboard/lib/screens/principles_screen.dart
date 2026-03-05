import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/principles_provider.dart';
import '../providers/locale_provider.dart';
import '../models/principles_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../animations/animation_utils.dart';

/// 매매 원칙 관리 화면이다.
class PrinciplesScreen extends StatefulWidget {
  const PrinciplesScreen({super.key});

  @override
  State<PrinciplesScreen> createState() => _PrinciplesScreenState();
}

class _PrinciplesScreenState extends State<PrinciplesScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<PrinciplesProvider>().load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = context.watch<LocaleProvider>().t;

    return Scaffold(
      backgroundColor: context.tc.background,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(context, t),
          _buildFilterChips(context, t),
          Expanded(
            child: _buildBody(context, t),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context, String Function(String) t) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
      decoration: BoxDecoration(
        color: context.tc.background,
        border: Border(
          bottom: BorderSide(
            color: context.tc.surfaceBorder.withValues(alpha: 0.3),
            width: 1,
          ),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(t('principles'), style: AppTypography.displayMedium),
                AppSpacing.vGapXs,
                Text(
                  '매매 시스템의 핵심 원칙 및 규칙 관리',
                  style: AppTypography.bodySmall,
                ),
              ],
            ),
          ),
          // 새로고침 버튼
          IconButton(
            icon: Icon(Icons.refresh_rounded,
                size: 20, color: context.tc.textTertiary),
            onPressed: () => context.read<PrinciplesProvider>().refresh(),
            tooltip: t('refresh'),
          ),
          AppSpacing.hGapSm,
          // 원칙 추가 버튼
          _AddPrincipleButton(t: t),
        ],
      ),
    );
  }

  Widget _buildFilterChips(BuildContext context, String Function(String) t) {
    return Consumer<PrinciplesProvider>(
      builder: (context, provider, _) {
        final categories = [
          ('all', t('categoryAll')),
          ('survival', t('categorySurvival')),
          ('risk', t('categoryRisk')),
          ('strategy', t('categoryStrategy')),
          ('execution', t('categoryExecution')),
        ];

        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: context.tc.surfaceBorder.withValues(alpha: 0.2),
                width: 1,
              ),
            ),
          ),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: categories.map((entry) {
                final key = entry.$1;
                final label = entry.$2;
                final isSelected = provider.selectedCategory == key;

                Color chipColor = context.tc.primary;
                if (key == 'survival') chipColor = context.tc.loss;
                if (key == 'risk') chipColor = context.tc.warning;
                if (key == 'strategy') chipColor = context.tc.primary;
                if (key == 'execution') chipColor = context.tc.profit;

                return Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: GestureDetector(
                    onTap: () => provider.setCategory(key),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 150),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: isSelected
                            ? (key == 'all'
                                ? context.tc.primary.withValues(alpha: 0.15)
                                : chipColor.withValues(alpha: 0.15))
                            : context.tc.surface,
                        borderRadius: AppSpacing.borderRadiusFull,
                        border: Border.all(
                          color: isSelected
                              ? (key == 'all'
                                  ? context.tc.primary.withValues(alpha: 0.40)
                                  : chipColor.withValues(alpha: 0.40))
                              : context.tc.surfaceBorder.withValues(alpha: 0.35),
                          width: 1,
                        ),
                      ),
                      child: Text(
                        label,
                        style: AppTypography.labelMedium.copyWith(
                          fontSize: 12,
                          color: isSelected
                              ? (key == 'all' ? context.tc.primary : chipColor)
                              : context.tc.textSecondary,
                        ),
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
        );
      },
    );
  }

  Widget _buildBody(BuildContext context, String Function(String) t) {
    return Consumer<PrinciplesProvider>(
      builder: (context, provider, _) {
        if (provider.isLoading && provider.data == null) {
          return _buildLoadingState();
        }

        if (provider.error != null && provider.data == null) {
          return _buildErrorState(context, provider, t);
        }

        final principles = provider.filteredPrinciples;

        if (principles.isEmpty && !provider.isLoading) {
          return _buildEmptyState(context, provider, t);
        }

        return _buildPrinciplesList(context, provider, principles, t);
      },
    );
  }

  Widget _buildLoadingState() {
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: 5,
      itemBuilder: (_, i) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: ShimmerLoading(
          width: double.infinity,
          height: 110,
          borderRadius: AppSpacing.borderRadiusMd,
        ),
      ),
    );
  }

  Widget _buildErrorState(
    BuildContext context,
    PrinciplesProvider provider,
    String Function(String) t,
  ) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.cloud_off_rounded, size: 48, color: context.tc.textTertiary),
          AppSpacing.vGapLg,
          Text(t('connection_error'), style: AppTypography.headlineMedium),
          AppSpacing.vGapSm,
          Text(provider.error ?? '', style: AppTypography.bodySmall),
          AppSpacing.vGapXxl,
          ElevatedButton.icon(
            onPressed: () => provider.load(),
            icon: const Icon(Icons.refresh_rounded, size: 18),
            label: Text(t('retry')),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyState(
    BuildContext context,
    PrinciplesProvider provider,
    String Function(String) t,
  ) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.gavel_rounded, size: 48, color: context.tc.textTertiary),
          AppSpacing.vGapLg,
          Text('원칙이 없습니다', style: AppTypography.bodyMedium),
          AppSpacing.vGapSm,
          Text(
            provider.selectedCategory == 'all'
                ? '원칙 추가 버튼으로 새 원칙을 등록하세요.'
                : '이 카테고리에 원칙이 없습니다.',
            style: AppTypography.bodySmall,
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }

  Widget _buildPrinciplesList(
    BuildContext context,
    PrinciplesProvider provider,
    List<TradingPrinciple> principles,
    String Function(String) t,
  ) {
    // 코어 슬로건이 있으면 상단에 표시한다
    final corePrinciple = provider.corePrinciple;

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      itemCount: principles.length + (corePrinciple.isNotEmpty ? 1 : 0),
      itemBuilder: (context, index) {
        // 코어 슬로건 카드
        if (corePrinciple.isNotEmpty && index == 0) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _CorePrincipleCard(
              text: corePrinciple,
              t: t,
            ),
          );
        }

        final itemIndex =
            corePrinciple.isNotEmpty ? index - 1 : index;
        final principle = principles[itemIndex];

        return StaggeredFadeSlide(
          index: itemIndex,
          child: Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: _PrincipleCard(principle: principle, t: t),
          ),
        );
      },
    );
  }
}

// ── 원칙 추가 버튼 ──

class _AddPrincipleButton extends StatelessWidget {
  final String Function(String) t;

  const _AddPrincipleButton({required this.t});

  @override
  Widget build(BuildContext context) {
    return ElevatedButton.icon(
      onPressed: () => _showAddDialog(context),
      icon: const Icon(Icons.add_rounded, size: 16),
      label: Text(t('addPrinciple')),
      style: ElevatedButton.styleFrom(
        backgroundColor: context.tc.primary,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        shape: RoundedRectangleBorder(
          borderRadius: AppSpacing.borderRadiusMd,
        ),
        textStyle: AppTypography.labelLarge.copyWith(
          fontSize: 13,
          color: Colors.white,
        ),
      ),
    );
  }

  void _showAddDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => _PrincipleDialog(
        isEdit: false,
        onSave: (category, title, content) async {
          await context
              .read<PrinciplesProvider>()
              .addPrinciple(category, title, content);
        },
      ),
    );
  }
}

// ── 핵심 원칙 카드 ──

class _CorePrincipleCard extends StatelessWidget {
  final String text;
  final String Function(String) t;

  const _CorePrincipleCard({required this.text, required this.t});

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      backgroundColor: context.tc.primary.withValues(alpha: 0.08),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: context.tc.primary.withValues(alpha: 0.15),
              borderRadius: AppSpacing.borderRadiusMd,
            ),
            child: Icon(
              Icons.format_quote_rounded,
              size: 20,
              color: context.tc.primary,
            ),
          ),
          AppSpacing.hGapMd,
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '핵심 슬로건',
                  style: AppTypography.labelMedium.copyWith(
                    color: context.tc.primary,
                    fontSize: 11,
                  ),
                ),
                AppSpacing.vGapXs,
                Text(
                  text,
                  style: AppTypography.headlineMedium.copyWith(
                    color: context.tc.textPrimary,
                    fontStyle: FontStyle.italic,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── 원칙 카드 ──

class _PrincipleCard extends StatelessWidget {
  final TradingPrinciple principle;
  final String Function(String) t;

  const _PrincipleCard({required this.principle, required this.t});

  @override
  Widget build(BuildContext context) {
    final color = principle.categoryColor;

    return GlassCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 12, 10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 우선순위 배지
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.15),
                    borderRadius: AppSpacing.borderRadiusMd,
                    border: Border.all(
                      color: color.withValues(alpha: 0.3),
                      width: 1,
                    ),
                  ),
                  child: Center(
                    child: Text(
                      '${principle.priority}',
                      style: AppTypography.labelLarge.copyWith(
                        color: color,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ),
                AppSpacing.hGapMd,
                // 제목 + 내용
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        principle.title,
                        style: AppTypography.labelLarge.copyWith(
                          fontSize: 14,
                          height: 1.4,
                        ),
                      ),
                      AppSpacing.vGapXs,
                      Text(
                        principle.content,
                        style: AppTypography.bodyMedium.copyWith(
                          fontSize: 13,
                          height: 1.55,
                        ),
                      ),
                    ],
                  ),
                ),
                AppSpacing.hGapSm,
                // 액션 버튼 (시스템 원칙이 아닐 때)
                if (!principle.isSystem)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _ActionIconButton(
                        icon: Icons.edit_outlined,
                        color: context.tc.primary,
                        tooltip: t('editPrinciple'),
                        onTap: () => _showEditDialog(context),
                      ),
                      AppSpacing.hGapXs,
                      _ActionIconButton(
                        icon: Icons.delete_outline_rounded,
                        color: context.tc.loss,
                        tooltip: t('deletePrinciple'),
                        onTap: () => _showDeleteConfirm(context),
                      ),
                    ],
                  ),
              ],
            ),
          ),
          // 태그 행
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
            child: Row(
              children: [
                // 카테고리 칩
                _CategoryChip(principle: principle),
                AppSpacing.hGapSm,
                // 시스템 배지
                if (principle.isSystem)
                  _SystemBadge(t: t),
                // 비활성 배지
                if (!principle.enabled) ...[
                  AppSpacing.hGapSm,
                  _DisabledBadge(),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _showEditDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => _PrincipleDialog(
        isEdit: true,
        initialTitle: principle.title,
        initialContent: principle.content,
        initialCategory: principle.category,
        onSave: (category, title, content) async {
          await context.read<PrinciplesProvider>().updatePrinciple(
                principle.id,
                title: title,
                content: content,
              );
        },
      ),
    );
  }

  void _showDeleteConfirm(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => _DeleteConfirmDialog(
        principle: principle,
        onConfirm: () async {
          await context
              .read<PrinciplesProvider>()
              .deletePrinciple(principle.id);
        },
      ),
    );
  }
}

// ── 카테고리 칩 ──

class _CategoryChip extends StatelessWidget {
  final TradingPrinciple principle;

  const _CategoryChip({required this.principle});

  @override
  Widget build(BuildContext context) {
    final color = principle.categoryColor;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(
          color: color.withValues(alpha: 0.28),
          width: 1,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(principle.categoryIcon, size: 11, color: color),
          const SizedBox(width: 4),
          Text(
            principle.categoryLabel,
            style: AppTypography.bodySmall.copyWith(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

// ── 시스템 배지 ──

class _SystemBadge extends StatelessWidget {
  final String Function(String) t;

  const _SystemBadge({required this.t});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: context.tc.surfaceBorder.withValues(alpha: 0.4),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(
          color: context.tc.surfaceBorder.withValues(alpha: 0.6),
          width: 1,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.lock_outline_rounded,
              size: 11, color: context.tc.textTertiary),
          const SizedBox(width: 4),
          Text(
            t('systemPrinciple'),
            style: AppTypography.bodySmall.copyWith(
              color: context.tc.textTertiary,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

// ── 비활성 배지 ──

class _DisabledBadge extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: context.tc.textDisabled.withValues(alpha: 0.08),
        borderRadius: AppSpacing.borderRadiusFull,
        border: Border.all(
          color: context.tc.textDisabled.withValues(alpha: 0.2),
          width: 1,
        ),
      ),
      child: Text(
        '비활성',
        style: AppTypography.bodySmall.copyWith(
          color: context.tc.textDisabled,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

// ── 아이콘 액션 버튼 ──

class _ActionIconButton extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String tooltip;
  final VoidCallback onTap;

  const _ActionIconButton({
    required this.icon,
    required this.color,
    required this.tooltip,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: Colors.transparent,
        borderRadius: AppSpacing.borderRadiusSm,
        child: InkWell(
          onTap: onTap,
          borderRadius: AppSpacing.borderRadiusSm,
          child: Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.08),
              borderRadius: AppSpacing.borderRadiusSm,
            ),
            child: Icon(icon, size: 15, color: color),
          ),
        ),
      ),
    );
  }
}

// ── 원칙 추가 / 수정 다이얼로그 ──

class _PrincipleDialog extends StatefulWidget {
  final bool isEdit;
  final String? initialCategory;
  final String? initialTitle;
  final String? initialContent;
  final Future<void> Function(String category, String title, String content)
      onSave;

  const _PrincipleDialog({
    required this.isEdit,
    this.initialCategory,
    this.initialTitle,
    this.initialContent,
    required this.onSave,
  });

  @override
  State<_PrincipleDialog> createState() => _PrincipleDialogState();
}

class _PrincipleDialogState extends State<_PrincipleDialog> {
  late String _selectedCategory;
  late final TextEditingController _titleController;
  late final TextEditingController _contentController;
  bool _isSaving = false;
  String? _errorText;

  // 사용자가 추가 가능한 카테고리 (생존은 시스템 전용)
  static const _availableCategories = ['risk', 'strategy', 'execution'];

  @override
  void initState() {
    super.initState();
    _selectedCategory = widget.initialCategory != null &&
            _availableCategories.contains(widget.initialCategory)
        ? widget.initialCategory!
        : 'risk';
    _titleController = TextEditingController(text: widget.initialTitle ?? '');
    _contentController =
        TextEditingController(text: widget.initialContent ?? '');
  }

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  String _categoryLabel(String cat) {
    switch (cat) {
      case 'risk':
        return '리스크';
      case 'strategy':
        return '전략';
      case 'execution':
        return '실행';
      default:
        return cat;
    }
  }

  Color _categoryColor(String cat) {
    switch (cat) {
      case 'risk':
        return context.tc.warning;
      case 'strategy':
        return context.tc.primary;
      case 'execution':
        return context.tc.profit;
      default:
        return context.tc.primary;
    }
  }

  Future<void> _handleSave() async {
    final title = _titleController.text.trim();
    final content = _contentController.text.trim();

    if (title.isEmpty) {
      setState(() => _errorText = '제목을 입력하세요.');
      return;
    }
    if (content.isEmpty) {
      setState(() => _errorText = '내용을 입력하세요.');
      return;
    }

    setState(() {
      _isSaving = true;
      _errorText = null;
    });

    try {
      await widget.onSave(_selectedCategory, title, content);
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      setState(() {
        _errorText = '저장 실패: ${e.toString()}';
        _isSaving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.read<LocaleProvider>().t;

    return Dialog(
      backgroundColor: context.tc.surfaceElevated,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusLg,
        side: BorderSide(color: context.tc.glassBorder, width: 1),
      ),
      child: SizedBox(
        width: 480,
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 다이얼로그 헤더
              Row(
                children: [
                  Icon(
                    widget.isEdit
                        ? Icons.edit_rounded
                        : Icons.add_circle_outline_rounded,
                    size: 20,
                    color: context.tc.primary,
                  ),
                  AppSpacing.hGapMd,
                  Text(
                    widget.isEdit ? t('editPrinciple') : t('addPrinciple'),
                    style: AppTypography.headlineMedium,
                  ),
                  const Spacer(),
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: Icon(Icons.close_rounded,
                        size: 18, color: context.tc.textTertiary),
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(),
                  ),
                ],
              ),
              AppSpacing.vGapXxl,

              // 카테고리 선택
              Text(
                t('principleCategory'),
                style: AppTypography.labelMedium.copyWith(
                  color: context.tc.textSecondary,
                ),
              ),
              AppSpacing.vGapSm,
              Row(
                children: _availableCategories.map((cat) {
                  final isSelected = _selectedCategory == cat;
                  final color = _categoryColor(cat);
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: GestureDetector(
                      onTap: () => setState(() => _selectedCategory = cat),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 150),
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 7),
                        decoration: BoxDecoration(
                          color: isSelected
                              ? color.withValues(alpha: 0.15)
                              : context.tc.surface,
                          borderRadius: AppSpacing.borderRadiusMd,
                          border: Border.all(
                            color: isSelected
                                ? color.withValues(alpha: 0.45)
                                : context.tc.surfaceBorder.withValues(alpha: 0.35),
                            width: 1,
                          ),
                        ),
                        child: Text(
                          _categoryLabel(cat),
                          style: AppTypography.labelMedium.copyWith(
                            fontSize: 13,
                            color: isSelected ? color : context.tc.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  );
                }).toList(),
              ),
              AppSpacing.vGapLg,

              // 제목 입력
              Text(
                t('principleTitle'),
                style: AppTypography.labelMedium.copyWith(
                  color: context.tc.textSecondary,
                ),
              ),
              AppSpacing.vGapSm,
              _StyledTextField(
                controller: _titleController,
                hintText: '원칙의 핵심 제목을 입력하세요',
                maxLines: 1,
              ),
              AppSpacing.vGapLg,

              // 내용 입력
              Text(
                t('principleContent'),
                style: AppTypography.labelMedium.copyWith(
                  color: context.tc.textSecondary,
                ),
              ),
              AppSpacing.vGapSm,
              _StyledTextField(
                controller: _contentController,
                hintText: '원칙의 상세 내용을 입력하세요',
                maxLines: 4,
              ),

              // 에러 텍스트
              if (_errorText != null) ...[
                AppSpacing.vGapMd,
                Text(
                  _errorText ?? '',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.loss,
                  ),
                ),
              ],

              AppSpacing.vGapXxl,

              // 버튼 행
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed:
                        _isSaving ? null : () => Navigator.of(context).pop(),
                    child: Text(
                      t('cancel'),
                      style: AppTypography.labelLarge.copyWith(
                        color: context.tc.textSecondary,
                      ),
                    ),
                  ),
                  AppSpacing.hGapMd,
                  ElevatedButton(
                    onPressed: _isSaving ? null : _handleSave,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: context.tc.primary,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 20, vertical: 10),
                      shape: RoundedRectangleBorder(
                        borderRadius: AppSpacing.borderRadiusMd,
                      ),
                    ),
                    child: _isSaving
                        ? SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Text(
                            t('save'),
                            style: AppTypography.labelLarge.copyWith(
                              color: Colors.white,
                              fontSize: 13,
                            ),
                          ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── 삭제 확인 다이얼로그 ──

class _DeleteConfirmDialog extends StatefulWidget {
  final TradingPrinciple principle;
  final Future<void> Function() onConfirm;

  const _DeleteConfirmDialog({
    required this.principle,
    required this.onConfirm,
  });

  @override
  State<_DeleteConfirmDialog> createState() => _DeleteConfirmDialogState();
}

class _DeleteConfirmDialogState extends State<_DeleteConfirmDialog> {
  bool _isDeleting = false;
  String? _errorText;

  Future<void> _handleDelete() async {
    setState(() {
      _isDeleting = true;
      _errorText = null;
    });

    try {
      await widget.onConfirm();
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      setState(() {
        _errorText = '삭제 실패: ${e.toString()}';
        _isDeleting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.read<LocaleProvider>().t;
    final color = widget.principle.categoryColor;

    return Dialog(
      backgroundColor: context.tc.surfaceElevated,
      shape: RoundedRectangleBorder(
        borderRadius: AppSpacing.borderRadiusLg,
        side: BorderSide(
          color: context.tc.loss.withValues(alpha: 0.3),
          width: 1,
        ),
      ),
      child: SizedBox(
        width: 400,
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: context.tc.loss.withValues(alpha: 0.12),
                      borderRadius: AppSpacing.borderRadiusMd,
                    ),
                    child: Icon(
                      Icons.delete_outline_rounded,
                      size: 18,
                      color: context.tc.loss,
                    ),
                  ),
                  AppSpacing.hGapMd,
                  Text(
                    t('deletePrinciple'),
                    style: AppTypography.headlineMedium,
                  ),
                ],
              ),
              AppSpacing.vGapXxl,

              // 삭제 대상 원칙 미리보기
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.06),
                  borderRadius: AppSpacing.borderRadiusMd,
                  border: Border.all(
                    color: color.withValues(alpha: 0.2),
                    width: 1,
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.principle.title,
                      style: AppTypography.labelLarge.copyWith(fontSize: 13),
                    ),
                    AppSpacing.vGapXs,
                    Text(
                      widget.principle.content,
                      style: AppTypography.bodySmall,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              AppSpacing.vGapMd,
              Text(
                t('confirmDelete'),
                style: AppTypography.bodyMedium,
              ),

              // 에러 텍스트
              if (_errorText != null) ...[
                AppSpacing.vGapMd,
                Text(
                  _errorText ?? '',
                  style: AppTypography.bodySmall.copyWith(
                    color: context.tc.loss,
                  ),
                ),
              ],

              AppSpacing.vGapXxl,
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: _isDeleting
                        ? null
                        : () => Navigator.of(context).pop(),
                    child: Text(
                      t('cancel'),
                      style: AppTypography.labelLarge.copyWith(
                        color: context.tc.textSecondary,
                      ),
                    ),
                  ),
                  AppSpacing.hGapMd,
                  ElevatedButton(
                    onPressed: _isDeleting ? null : _handleDelete,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: context.tc.loss,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 20, vertical: 10),
                      shape: RoundedRectangleBorder(
                        borderRadius: AppSpacing.borderRadiusMd,
                      ),
                    ),
                    child: _isDeleting
                        ? SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Text(
                            t('delete'),
                            style: AppTypography.labelLarge.copyWith(
                              color: Colors.white,
                              fontSize: 13,
                            ),
                          ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── 스타일 적용 텍스트 필드 ──

class _StyledTextField extends StatelessWidget {
  final TextEditingController controller;
  final String hintText;
  final int maxLines;

  const _StyledTextField({
    required this.controller,
    required this.hintText,
    required this.maxLines,
  });

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      maxLines: maxLines,
      minLines: maxLines == 1 ? 1 : 3,
      style: AppTypography.bodyMedium.copyWith(
        color: context.tc.textPrimary,
        fontSize: 14,
      ),
      decoration: InputDecoration(
        hintText: hintText,
        hintStyle: AppTypography.bodyMedium.copyWith(
          color: context.tc.textDisabled,
          fontSize: 14,
        ),
        filled: true,
        fillColor: context.tc.surface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 14,
          vertical: 12,
        ),
        border: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: BorderSide(
            color: context.tc.surfaceBorder.withValues(alpha: 0.5),
            width: 1,
          ),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: BorderSide(
            color: context.tc.surfaceBorder.withValues(alpha: 0.5),
            width: 1,
          ),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: AppSpacing.borderRadiusMd,
          borderSide: BorderSide(
            color: context.tc.primary.withValues(alpha: 0.6),
            width: 1.5,
          ),
        ),
      ),
      cursorColor: context.tc.primary,
    );
  }
}

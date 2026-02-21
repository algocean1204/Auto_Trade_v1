import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/indicator_provider.dart';
import '../models/indicator_models.dart';
import '../theme/trading_colors.dart';
import '../theme/app_typography.dart';
import '../theme/app_spacing.dart';
import '../widgets/glass_card.dart';
import '../widgets/weight_slider.dart';
import '../animations/animation_utils.dart';

class IndicatorSettings extends StatefulWidget {
  const IndicatorSettings({super.key});

  @override
  State<IndicatorSettings> createState() => _IndicatorSettingsState();
}

class _IndicatorSettingsState extends State<IndicatorSettings> {
  Map<String, double> _editedWeights = {};
  Map<String, bool> _enabledIndicators = {};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<IndicatorProvider>().loadWeights();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Indicators', style: AppTypography.displaySmall),
        actions: [
          TextButton.icon(
            onPressed: () => _saveWeights(),
            icon: const Icon(Icons.save_rounded, size: 18),
            label: const Text('Save'),
          ),
        ],
      ),
      body: Consumer<IndicatorProvider>(
        builder: (context, provider, child) {
          if (provider.isLoading && provider.weights == null) {
            return _buildLoadingSkeleton();
          }

          if (provider.error != null && provider.weights == null) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.cloud_off_rounded, size: 48, color: context.tc.textTertiary),
                  AppSpacing.vGapLg,
                  Text('Error: ${provider.error}', style: AppTypography.bodyMedium),
                  AppSpacing.vGapLg,
                  ElevatedButton(
                    onPressed: () => provider.loadWeights(),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            );
          }

          final weights = provider.weights;
          if (weights == null) {
            return Center(child: Text('No data', style: AppTypography.bodyLarge));
          }

          if (_editedWeights.isEmpty) {
            _editedWeights = Map.from(weights.weights);
            _enabledIndicators = weights.weights.map(
              (key, value) => MapEntry(key, value > 0),
            );
          }

          return ListView(
            padding: AppSpacing.paddingScreen,
            children: [
              StaggeredFadeSlide(
                index: 0,
                child: _buildPresetSection(weights.presets),
              ),
              AppSpacing.vGapXxl,
              StaggeredFadeSlide(
                index: 1,
                child: _buildCategorySection('Momentum', IndicatorCategory.momentum),
              ),
              AppSpacing.vGapXxl,
              StaggeredFadeSlide(
                index: 2,
                child: _buildCategorySection('Trend', IndicatorCategory.trend),
              ),
              AppSpacing.vGapXxl,
              StaggeredFadeSlide(
                index: 3,
                child: _buildCategorySection('Volatility', IndicatorCategory.volatility),
              ),
              AppSpacing.vGapXxl,
            ],
          );
        },
      ),
    );
  }

  Widget _buildLoadingSkeleton() {
    return Padding(
      padding: AppSpacing.paddingScreen,
      child: Column(
        children: [
          ShimmerLoading(width: double.infinity, height: 80, borderRadius: AppSpacing.borderRadiusLg),
          AppSpacing.vGapLg,
          ShimmerLoading(width: double.infinity, height: 200, borderRadius: AppSpacing.borderRadiusLg),
          AppSpacing.vGapLg,
          ShimmerLoading(width: double.infinity, height: 200, borderRadius: AppSpacing.borderRadiusLg),
        ],
      ),
    );
  }

  Widget _buildPresetSection(List<WeightPreset> presets) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Presets', style: AppTypography.headlineMedium),
          AppSpacing.vGapMd,
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: presets.map((preset) {
              return ActionChip(
                label: Text(preset.name),
                onPressed: () => _applyPreset(preset),
                side: BorderSide(color: context.tc.primary.withValues(alpha: 0.3)),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildCategorySection(String title, IndicatorCategory category) {
    final indicators = IndicatorInfo.all
        .where((info) => info.category == category)
        .toList();

    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: AppTypography.headlineMedium),
          AppSpacing.vGapLg,
          ...indicators.map((info) => _buildIndicatorItem(info)),
        ],
      ),
    );
  }

  Widget _buildIndicatorItem(IndicatorInfo info) {
    final enabled = _enabledIndicators[info.id] ?? false;
    final weight = _editedWeights[info.id] ?? 0.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    info.displayName,
                    style: AppTypography.labelLarge,
                  ),
                  AppSpacing.vGapXs,
                  Text(
                    info.description,
                    style: AppTypography.bodySmall,
                  ),
                ],
              ),
            ),
            Switch(
              value: enabled,
              onChanged: (value) {
                setState(() {
                  _enabledIndicators[info.id] = value;
                  if (!value) {
                    _editedWeights[info.id] = 0.0;
                  } else if (_editedWeights[info.id] == 0.0) {
                    _editedWeights[info.id] = 20.0;
                  }
                });
              },
            ),
          ],
        ),
        AppSpacing.vGapSm,
        WeightSlider(
          label: 'Weight',
          value: weight,
          enabled: enabled,
          onChanged: (value) {
            setState(() {
              _editedWeights[info.id] = value;
            });
          },
        ),
        Divider(
          height: 32,
          color: context.tc.surfaceBorder.withValues(alpha: 0.3),
        ),
      ],
    );
  }

  void _applyPreset(WeightPreset preset) {
    setState(() {
      _editedWeights = Map.from(preset.weights);
      _enabledIndicators = preset.weights.map(
        (key, value) => MapEntry(key, value > 0),
      );
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Applied: ${preset.name}'),
        backgroundColor: context.tc.primary,
      ),
    );
  }

  void _saveWeights() async {
    try {
      await context.read<IndicatorProvider>().updateWeights(_editedWeights);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Weights saved'),
            backgroundColor: context.tc.profit,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Save failed: $e'),
            backgroundColor: context.tc.loss,
          ),
        );
      }
    }
  }
}

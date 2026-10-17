import 'package:flutter/material.dart';

import '../services/pqf_api.dart';

/// "Why this score": every criterion of the framework for one photo, with its value,
/// the pass threshold the server states (GET /criteria) and a pass or fail tick.
///
/// DISPLAY ONLY. It reads scores the framework already computed and thresholds the
/// server already serves. It decides nothing, writes nothing and cannot change which
/// photos are selected or certified. Shown so a reader can see the stated standard
/// being applied, criterion by criterion.
class BreakdownPanel extends StatelessWidget {
  final BatchPhoto photo;

  /// TQS / SQS / FQS of this photo from the /batch result (null if not reported).
  final BatchImageResult? scores;

  /// The criteria in force; null when /criteria could not be read, in which case the
  /// values are shown without thresholds (the app never hard-codes a threshold).
  final CriteriaInfo? criteria;

  /// Called when the panel is opened (the screen pauses its auto-advance).
  final VoidCallback? onOpened;

  const BreakdownPanel({
    super.key,
    required this.photo,
    required this.scores,
    required this.criteria,
    this.onOpened,
  });

  static const technicalOrder = [
    ('sharpness', 'T1 Sharpness'),
    ('exposure', 'T2 Exposure'),
    ('background', 'T3 Background'),
    ('brisque', 'T4 BRISQUE'),
    ('piqe', 'T5 PIQE'),
    ('colorcast', 'T6 Colour cast'),
  ];
  static const semanticOrder = [
    ('subject_centering', 'S1 Centring'),
    ('feature_visibility', 'S2 Feature visibility'),
    ('marketing_suitability', 'S3 Marketing suitability'),
    ('angle_value', 'S4 Angle value'),
    ('lighting_style_quality', 'S5 Lighting and style'),
  ];

  CriterionInfo? _info(List<CriterionInfo>? list, String name) {
    if (list == null) return null;
    for (final c in list) {
      if (c.name == name) return c;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final fqsLine = criteria?.fqsPass;
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 10),
        childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        dense: true,
        title: const Text('Why this score',
            style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600)),
        onExpansionChanged: (open) {
          if (open) onOpened?.call();
        },
        children: [
          _Totals(photo: photo, scores: scores, fqsPass: fqsLine),
          const SizedBox(height: 10),
          _Group(
            title: 'Technical',
            rows: [
              for (final (key, label) in technicalOrder)
                _Row(
                  label: label,
                  value: photo.technical[key],
                  threshold: _info(criteria?.technical, key)?.passThreshold,
                  weight: _info(criteria?.technical, key)?.weight,
                  thresholdKnown: criteria != null,
                ),
            ],
          ),
          const SizedBox(height: 8),
          _Group(
            title: 'Semantic',
            rows: [
              for (final (key, label) in semanticOrder)
                _Row(
                  label: label,
                  value: photo.semantic[key],
                  threshold: _info(criteria?.semantic, key)?.passThreshold,
                  weight: _info(criteria?.semantic, key)?.weight,
                  thresholdKnown: criteria != null,
                ),
            ],
          ),
          if (criteria == null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                  'Thresholds could not be read from the server, so no pass or '
                  'fail marks are shown.',
                  style: TextStyle(fontSize: 12, color: Colors.grey.shade700)),
            ),
        ],
      ),
    );
  }
}

class _Totals extends StatelessWidget {
  final BatchPhoto photo;
  final BatchImageResult? scores;
  final double? fqsPass;

  const _Totals(
      {required this.photo, required this.scores, required this.fqsPass});

  String _f(double? v) => v == null ? '–' : v.toStringAsFixed(2);

  @override
  Widget build(BuildContext context) {
    final fqs = scores?.fqs ?? photo.fqs;
    final passes = fqsPass != null && fqs >= fqsPass!;
    const mono = TextStyle(fontSize: 12.5, fontFamily: 'monospace');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('TQS ${_f(scores?.tqs)}   SQS ${_f(scores?.sqs)}   FQS ${_f(fqs)}',
            style: mono.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 3),
        Row(children: [
          Text(
              fqsPass == null
                  ? 'FQS pass line unavailable'
                  : 'FQS pass line ${_f(fqsPass)}',
              style: mono),
          const SizedBox(width: 8),
          if (fqsPass != null)
            _Tick(ok: passes, label: passes ? 'FQS at or above the line' : 'FQS below the line'),
        ]),
      ],
    );
  }
}

class _Group extends StatelessWidget {
  final String title;
  final List<_Row> rows;

  const _Group({required this.title, required this.rows});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: Colors.grey.shade700)),
          const SizedBox(height: 4),
          ...rows,
        ],
      );
}

class _Row extends StatelessWidget {
  final String label;
  final double? value;
  final double? threshold;
  final double? weight;
  final bool thresholdKnown;

  const _Row({
    required this.label,
    required this.value,
    required this.threshold,
    required this.weight,
    required this.thresholdKnown,
  });

  @override
  Widget build(BuildContext context) {
    final v = value;
    final t = threshold;
    final bool? ok = (v != null && t != null) ? v >= t : null;
    const mono = TextStyle(fontSize: 12.5, fontFamily: 'monospace');
    final reportedOnly = weight != null && weight == 0.0;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2.5),
      child: Row(children: [
        Expanded(
          child: Text(reportedOnly ? '$label (reported only)' : label,
              style: const TextStyle(fontSize: 13)),
        ),
        SizedBox(
            width: 46,
            child: Text(v == null ? '–' : v.toStringAsFixed(2),
                textAlign: TextAlign.right, style: mono)),
        SizedBox(
            width: 74,
            child: Text(t == null ? (thresholdKnown ? 'no line' : '–') : '≥ ${t.toStringAsFixed(2)}',
                textAlign: TextAlign.right,
                style: mono.copyWith(color: Colors.grey.shade700))),
        const SizedBox(width: 8),
        SizedBox(
            width: 22,
            child: ok == null
                ? Text(v == null ? 'n/a' : '', style: mono)
                : _Tick(ok: ok, label: ok ? '$label passes' : '$label below its threshold')),
      ]),
    );
  }
}

class _Tick extends StatelessWidget {
  final bool ok;
  final String label;

  const _Tick({required this.ok, required this.label});

  @override
  Widget build(BuildContext context) => Semantics(
        label: label,
        child: Icon(ok ? Icons.check_circle : Icons.cancel,
            size: 18,
            color: ok ? const Color(0xFF2E7D32) : const Color(0xFFB3261E)),
      );
}

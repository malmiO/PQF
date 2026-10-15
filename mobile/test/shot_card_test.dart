import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/shot_plan.dart';
import 'package:mobile/widgets/help_sheet.dart';
import 'package:mobile/widgets/shot_card.dart';

/// The card before every shot (2026-10-15): the same shot name and one-line description
/// in the unguided and the guided condition; the guided extras only in the guided one.
void main() {
  Widget host(ShotStep step, {required bool guided, int n = 1, bool optional = false}) =>
      MaterialApp(
        home: Scaffold(
          body: ShotCard(
            step: step,
            guided: guided,
            shotNumber: n,
            total: ShotPlan.steps.length,
            optional: optional,
            canFinishInstead: false,
            onReady: () {},
            onFinish: () {},
          ),
        ),
      );

  List<String> coreText(WidgetTester tester) => tester
      .widgetList<Text>(find.descendant(
          of: find.byKey(ShotCard.coreKey), matching: find.byType(Text)))
      .map((t) => t.data ?? '')
      .toList();

  for (var i = 0; i < ShotPlan.steps.length; i++) {
    final step = ShotPlan.steps[i];

    testWidgets('${step.label}: the core text is identical in A and B', (tester) async {
      await tester.pumpWidget(host(step, guided: false, n: i + 1, optional: i >= 4));
      final a = coreText(tester);
      await tester.pumpWidget(host(step, guided: true, n: i + 1, optional: i >= 4));
      final b = coreText(tester);
      expect(a, [step.label, step.instruction]);
      expect(b, a, reason: 'condition A and B read the same words for this shot');
    });

    testWidgets('${step.label}: A shows nothing but the card, B adds its extras',
        (tester) async {
      await tester.pumpWidget(host(step, guided: false, n: i + 1, optional: i >= 4));
      final textA = tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => t.data ?? '')
          .toList();
      // the shot name, its one line, and the button: nothing measured, nothing explained
      expect(textA, [step.label, step.instruction, 'I am ready']);
      expect(find.byType(ReferenceImage), findsNothing);
      expect(find.byIcon(Icons.lightbulb_outline), findsNothing);

      await tester.pumpWidget(host(step, guided: true, n: i + 1, optional: i >= 4));
      final textB = tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => t.data ?? '')
          .join('\n');
      expect(textB, contains(step.label));
      expect(textB, contains(step.instruction));
      expect(textB, contains(step.why));
      expect(textB, contains('the camera will check the shot'));
      expect(textB, contains(i >= 4 ? 'Optional extra shot' : 'Shot ${i + 1} of '));
    });
  }

  test('the detail card tells both conditions to fill the frame with one feature', () {
    final detail = ShotPlan.steps.firstWhere((s) => s.label == 'Detail');
    expect(detail.instruction.toLowerCase(), contains('one feature, close up'));
  });

  test('the card cannot reach the network or the guidance endpoint', () {
    final src = File('lib/widgets/shot_card.dart').readAsStringSync();
    for (final banned in ['PqfApi', 'guidance(', 'http', 'ApiConfig', 'StudySession']) {
      expect(src.contains(banned), isFalse, reason: 'shot_card.dart mentions $banned');
    }
  });

  test('the capture screen shows the card in both conditions and still never asks A '
      'for guidance', () {
    final src = File('lib/screens/capture_screen.dart').readAsStringSync();
    expect(src.contains('class _Briefing'), isFalse);
    expect(src.contains('_showBriefing = _guided'), isFalse);
    expect(RegExp(r'_showBriefing = true; // the same card').allMatches(src).length, 2);
    expect(src.contains('ShotCard('), isTrue);
    expect(src.contains('if (!_guided) return; // UNGUIDED: never ask for guidance'),
        isTrue);
  });
}

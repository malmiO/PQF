import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/study_session.dart';
import 'package:mobile/screens/results_screen.dart';
import 'package:mobile/services/pqf_api.dart';
import 'package:mobile/widgets/breakdown_panel.dart';

/// "Why this score" (v1.4.0): every criterion of the framework for each photo, with its
/// value, the server's pass threshold and a tick. DISPLAY ONLY.
///
/// The fixture is the real output of POST /batch and GET /criteria for a four photo
/// earrings set (backend run with the mock semantic evaluator, so the semantic VALUES
/// are arbitrary; the shape, the thresholds and the technical scores are real).
void main() {
  late Map<String, dynamic> fx;
  late BatchResult batch;
  late CriteriaInfo criteria;

  setUpAll(() {
    fx = jsonDecode(File('test/fixtures/batch_breakdown.json').readAsStringSync())
        as Map<String, dynamic>;
    batch = BatchResult.fromJson(fx['batch'] as Map<String, dynamic>);
    criteria = CriteriaInfo.fromJson(fx['criteria'] as Map<String, dynamic>);
  });

  BatchImageResult? scoresFor(BatchPhoto p) {
    for (final s in batch.selected) {
      if (s.index == p.index) return s;
    }
    return null;
  }

  Widget host(Widget child) => MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: child)));

  const technicalLabels = [
    'T1 Sharpness',
    'T2 Exposure',
    'T3 Background',
    'T4 BRISQUE',
    'T5 PIQE',
    'T6 Colour cast',
  ];
  const semanticLabels = [
    'S1 Centring',
    'S2 Feature visibility',
    'S3 Marketing suitability',
    'S4 Angle value',
    'S5 Lighting and style',
  ];

  test('the app reads the per-criterion scores and the server thresholds', () {
    final full = batch.images.firstWhere((p) => p.semantic.isNotEmpty);
    expect(full.technical.keys.toSet(), {
      'sharpness', 'exposure', 'background', 'brisque', 'piqe', 'colorcast'
    });
    expect(full.semantic.length, 5);
    final t = {for (final c in criteria.technical) c.name: c.passThreshold};
    expect(t['sharpness'], 0.20);
    expect(t['piqe'], 0.33);
    expect(t['brisque'], 0.0);
    expect(criteria.semantic.length, 5);
    expect(criteria.fqsPass, 0.55);
  });

  testWidgets('the panel lists all 11 criteria with value, threshold and a tick',
      (tester) async {
    final p = batch.images.firstWhere((p) => p.semantic.isNotEmpty);
    await tester.pumpWidget(host(BreakdownPanel(
        photo: p, scores: scoresFor(p), criteria: criteria)));
    expect(find.text('Why this score'), findsOneWidget);
    await tester.tap(find.text('Why this score'));
    await tester.pumpAndSettle();

    for (final l in [...technicalLabels, ...semanticLabels]) {
      // T4 is carried at weight 0 and says so
      expect(find.textContaining(l), findsOneWidget, reason: l);
    }
    expect(find.text('Technical'), findsOneWidget);
    expect(find.text('Semantic'), findsOneWidget);
    expect(find.textContaining('≥ '), findsNWidgets(11),
        reason: 'one threshold per criterion, read from /criteria');
    expect(find.textContaining('≥ 0.33'), findsOneWidget); // T5, calibrated
    expect(find.textContaining('(reported only)'), findsOneWidget); // T4, weight 0
    // 11 criteria ticks + the FQS tick
    final ticks = find.byWidgetPredicate((w) =>
        w is Icon &&
        (w.icon == Icons.check_circle || w.icon == Icons.cancel));
    expect(ticks, findsNWidgets(12));
    expect(find.textContaining('TQS'), findsOneWidget);
    expect(find.textContaining('SQS'), findsWidgets);
    expect(find.textContaining('FQS pass line 0.55'), findsOneWidget);
  });

  testWidgets('a hard-rejected photo shows its technical scores and "–" for the rest',
      (tester) async {
    final p = batch.images.firstWhere((p) => p.semantic.isEmpty);
    await tester.pumpWidget(host(BreakdownPanel(
        photo: p, scores: scoresFor(p), criteria: criteria)));
    await tester.tap(find.text('Why this score'));
    await tester.pumpAndSettle();
    for (final l in technicalLabels) {
      expect(find.textContaining(l), findsOneWidget);
    }
    // five semantic rows, no value, no tick
    expect(find.text('n/a'), findsNWidgets(5));
  });

  testWidgets('without /criteria the values show and no pass or fail is invented',
      (tester) async {
    final p = batch.images.firstWhere((p) => p.semantic.isNotEmpty);
    await tester.pumpWidget(
        host(BreakdownPanel(photo: p, scores: scoresFor(p), criteria: null)));
    await tester.tap(find.text('Why this score'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Thresholds could not be read'), findsOneWidget);
    expect(find.byIcon(Icons.cancel), findsNothing);
    expect(find.textContaining('≥ '), findsNothing);
  });

  testWidgets('on the results screen: a panel under each photo, selection untouched',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    final tiny = Uint8List.fromList(base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='));
    await tester.pumpWidget(MaterialApp(
      home: ResultsScreen(
        draft: const ProductDraft(name: 'Pair of earrings'),
        result: batch,
        images: List.filled(4, tiny),
      ),
    ));
    await tester.pump();
    // the set card has its panel; the not-used cards sit in a collapsed tile
    expect(find.text('Why this score'), findsOneWidget);
    await tester.tap(find.textContaining('Not used'));
    await tester.pumpAndSettle();
    expect(find.text('Why this score'), findsNWidgets(1 + batch.notUsed.length));
    // what is in the set is exactly what the server decided
    expect(batch.setPhotos.map((p) => p.index).toList(),
        batch.images.where((p) => p.selected).map((p) => p.index).toList());
  });

  testWidgets('a certified set is not left before the breakdown can be read',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    final json = Map<String, dynamic>.from(fx['batch'] as Map<String, dynamic>);
    json['certified'] = true;
    final certified = BatchResult.fromJson(json);
    final tiny = Uint8List.fromList(base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='));
    await tester.pumpWidget(MaterialApp(
      home: ResultsScreen(
        draft: const ProductDraft(name: 'Pair of earrings'),
        result: certified,
        images: List.filled(4, tiny),
      ),
    ));
    await tester.pump();
    expect(find.text('Making your video next'), findsOneWidget);
    // opening a panel pauses the automatic move on; a button continues instead
    await tester.tap(find.text('Why this score'));
    await tester.pump(const Duration(seconds: 3)); // longer than the 1.5 s timer
    expect(find.text('Continue to your video'), findsOneWidget);
    expect(find.text('Making your video next'), findsNothing);
    expect(find.byType(ResultsScreen), findsOneWidget);
  });

  testWidgets('study mode: no "Why this score" panel anywhere on the results screen',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    StudySession.current =
        StudySession(participant: 'P01', product: 'K1', session: 1);
    addTearDown(() => StudySession.current = null);
    final tiny = Uint8List.fromList(base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='));
    await tester.pumpWidget(MaterialApp(
      home: ResultsScreen(
        draft: const ProductDraft(name: 'Pair of earrings'),
        result: batch,
        images: List.filled(4, tiny),
      ),
    ));
    await tester.pump();
    expect(find.byType(BreakdownPanel), findsNothing);
    expect(find.text('Why this score'), findsNothing);
    // the not-used cards are in a collapsed tile: open it and check again
    await tester.tap(find.textContaining('Not used'));
    await tester.pumpAndSettle();
    expect(find.byType(BreakdownPanel), findsNothing);
    expect(find.text('Why this score'), findsNothing);
    // the photos and their reasons are still shown
    expect(find.textContaining('Photo '), findsWidgets);
  });

  testWidgets('outside study mode the panel is shown again', (tester) async {
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    StudySession.current = null;
    final tiny = Uint8List.fromList(base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='));
    await tester.pumpWidget(MaterialApp(
      home: ResultsScreen(
        draft: const ProductDraft(name: 'Pair of earrings'),
        result: batch,
        images: List.filled(4, tiny),
      ),
    ));
    await tester.pump();
    expect(find.byType(BreakdownPanel), findsWidgets);
  });
}

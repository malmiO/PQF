import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/config/api_config.dart';
import 'package:mobile/models/study_session.dart';
import 'package:mobile/screens/home_screen.dart';

/// Study mode stays behind its PIN (v1.5.0: the visible "Join the study" button of
/// 2026-10-15 is gone; a long press on the title, or on the version line in Profile,
/// is the only way in). Nothing opens the study without the PIN.
void main() {
  const pin = '4321';

  Future<void> pumpHome(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
    await tester.pump();
  }

  void configurePin(bool on) {
    dotenv.testLoad(fileInput: on ? 'PQF_STUDY_PIN=$pin\n' : 'PQF_API_BASE_URL=http://x\n');
    ApiConfig.loaded = true;
  }

  setUp(() {
    StudySession.current = null;
    configurePin(true);
  });

  tearDown(() {
    StudySession.current = null;
    ApiConfig.loaded = false;
    dotenv.clean();
  });

  final routes = <String, Future<void> Function(WidgetTester)>{
    'a long press on the title': (t) async {
      await t.longPress(find.text('Éclat'));
    },
  };

  testWidgets('there is no visible Join the study button any more', (tester) async {
    await pumpHome(tester);
    expect(find.text('Join the study'), findsNothing);
  });

  for (final r in routes.entries) {
    testWidgets('${r.key} reaches the PIN prompt', (tester) async {
      await pumpHome(tester);
      await r.value(tester);
      await tester.pumpAndSettle();
      expect(find.text('Study mode'), findsOneWidget);
      expect(find.widgetWithText(TextField, ''), findsOneWidget);
      expect(find.text('PIN'), findsOneWidget);
      expect(find.text('Study session'), findsNothing, reason: 'not open yet');
    });

    testWidgets('${r.key}: a wrong PIN opens nothing', (tester) async {
      await pumpHome(tester);
      await r.value(tester);
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '0000');
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      expect(find.text('Wrong PIN.'), findsOneWidget);
      expect(find.text('Study session'), findsNothing);
      expect(StudySession.current, isNull);
    });

    testWidgets('${r.key}: cancelling opens nothing', (tester) async {
      await pumpHome(tester);
      await r.value(tester);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(find.text('Study session'), findsNothing);
      expect(find.text('Study mode'), findsNothing);
    });

    testWidgets('${r.key}: an empty PIN opens nothing', (tester) async {
      await pumpHome(tester);
      await r.value(tester);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      expect(find.text('Study session'), findsNothing);
    });

    testWidgets('${r.key}: the right PIN opens the researcher screen', (tester) async {
      await pumpHome(tester);
      await r.value(tester);
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), pin);
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      expect(find.text('Study session'), findsOneWidget);
      expect(find.text('Start session'), findsOneWidget);
    });

    testWidgets('${r.key}: with no PIN configured the study cannot be opened',
        (tester) async {
      configurePin(false);
      expect(ApiConfig.studyPin, isNull);
      await pumpHome(tester);
      await r.value(tester);
      await tester.pumpAndSettle();
      expect(find.textContaining('Study mode is not set up'), findsOneWidget);
      expect(find.text('Study mode'), findsNothing, reason: 'no PIN dialog to type into');
      expect(find.text('Study session'), findsNothing);
    });
  }

  test('the long presses call the one handler that asks for the PIN', () {
    final src = File('lib/screens/home_screen.dart').readAsStringSync();
    expect(src.contains('onLongPress: _joinStudy'), isTrue);
    expect(src.contains('Join the study'), isFalse);
    expect('openStudyMode('.allMatches(src).length, 1);
    final profile = File('lib/screens/profile_screen.dart').readAsStringSync();
    expect(profile.contains('onLongPress: () => openStudyMode(context)'), isTrue);
  });
}

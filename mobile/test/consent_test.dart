import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/screens/privacy_screen.dart';

void main() {
  group('consent versioning', () {
    test('no stored consent means not consented', () async {
      SharedPreferences.setMockInitialValues({});
      expect(await PrivacyScreen.consented(), isFalse);
    });

    test('an older accepted version requires re-consent', () async {
      SharedPreferences.setMockInitialValues(
          {'privacy_consent_version': PrivacyScreen.consentVersion - 1});
      expect(await PrivacyScreen.consented(), isFalse);
    });

    test('the current accepted version counts as consented', () async {
      SharedPreferences.setMockInitialValues(
          {'privacy_consent_version': PrivacyScreen.consentVersion});
      expect(await PrivacyScreen.consented(), isTrue);
    });

    test('a newer accepted version still counts as consented', () async {
      SharedPreferences.setMockInitialValues(
          {'privacy_consent_version': PrivacyScreen.consentVersion + 5});
      expect(await PrivacyScreen.consented(), isTrue);
    });
  });

  group('consent screen buttons', () {
    testWidgets('first run shows "I agree" and "Not now", not "Close"',
        (tester) async {
      SharedPreferences.setMockInitialValues({});
      await tester.pumpWidget(const MaterialApp(
        home: PrivacyScreen(firstRun: true),
      ));
      await tester.pump();
      expect(find.text('I agree'), findsOneWidget);
      expect(find.text('Not now'), findsOneWidget);
      expect(find.text('Close'), findsNothing);
    });

    testWidgets('read-only review shows only "Close"', (tester) async {
      SharedPreferences.setMockInitialValues({});
      await tester.pumpWidget(const MaterialApp(
        home: PrivacyScreen(firstRun: false),
      ));
      await tester.pump();
      expect(find.text('Close'), findsOneWidget);
      expect(find.text('I agree'), findsNothing);
    });

    testWidgets('the free-tier data-use sentence is shown', (tester) async {
      SharedPreferences.setMockInitialValues({});
      await tester.pumpWidget(const MaterialApp(
        home: PrivacyScreen(firstRun: true),
      ));
      await tester.pump();
      // Default tier is "free" when no config is loaded. The sentence sits lower
      // in the scrollable list, so scroll it into view before asserting.
      final sentence =
          find.textContaining('Google may keep the photos it receives');
      await tester.scrollUntilVisible(
        sentence,
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(sentence, findsOneWidget);
    });
  });
}

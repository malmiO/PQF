// Accessibility pass (v1.1.0, Part D4). Every screen that does not need the
// camera or the video player is drawn on a J6+ sized screen (360 x 740 dp) with
// the system text size at 1.3x, and checked against Flutter's built in
// guidelines: tap targets at least 48 dp, every tappable control labelled, and
// text contrast at least 4.5:1 (3:1 for large text). Any layout overflow at
// 1.3x also fails the test. Results are summarised in ACCESSIBILITY_CHECK.md.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/screens/business_profile_screen.dart';
import 'package:mobile/screens/auth_screen.dart';
import 'package:mobile/screens/profile_screen.dart';
import 'package:mobile/services/auth_service.dart';
import 'package:mobile/screens/home_screen.dart';
import 'package:mobile/screens/making_video_screen.dart';
import 'package:mobile/screens/mode_screen.dart';
import 'package:mobile/screens/onboarding_screen.dart';
import 'package:mobile/screens/privacy_screen.dart';
import 'package:mobile/screens/product_form_screen.dart';
import 'package:mobile/screens/results_screen.dart';
import 'package:mobile/screens/study_screens.dart';
import 'package:mobile/screens/upload_screen.dart';
import 'package:mobile/services/pqf_api.dart';

// A 1x1 white PNG, so image widgets have something real to decode.
final Uint8List png = Uint8List.fromList(const [
  0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49,
  0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x02,
  0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44,
  0x41, 0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F, 0x00, 0x05, 0xFE, 0x02,
  0xFE, 0xDC, 0xCC, 0x59, 0xE7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,
  0xAE, 0x42, 0x60, 0x82,
]);

const draft = ProductDraft(name: 'Teacher keychain', price: 'Rs. 450');

BatchResult result({required bool certified}) => BatchResult.fromJson({
      'certified': certified,
      'selected': [
        for (var i = 0; i < 5; i++)
          {'index': i, 'fqs': 0.8, 'tqs': 0.7, 'sqs': 0.8,
           'role': i == 0 ? 'hero_shot' : (i == 3 ? 'detail_shot' : 'angle_shot'),
           'passed': i < 4, 'reason': '', 'weakest': ''}
      ],
      'role_sets': <String, dynamic>{},
      'recapture': certified ? null : {'instruction': 'Take a close-up.'},
      'images': [
        for (var i = 0; i < 5; i++)
          {'index': i, 'name': 'capture_$i.jpg', 'fqs': 0.8, 'passed': i < 4,
           'role': i == 0 ? 'hero_shot' : (i == 3 ? 'detail_shot' : 'angle_shot'),
           'selected': i < 4 && certified,
           'status': i < 4 ? (certified ? 'selected' : 'not_needed') : 'same_view',
           'message': i < 4 ? 'Chosen: shows the product from another side.'
               : 'Not used: it shows the same view as photo 2, which is already in your set.'}
      ],
      'missing': certified ? [] : [
        {'role': 'detail_shot', 'count': 1,
         'message': 'Take a close-up of the most important detail, such as the '
             'texture, label or clasp.'}
      ],
    });

final screens = <String, Widget Function()>{
  'Home': () => const HomeScreen(),
  'Product details': () => const ProductFormScreen(),
  'Mode': () => const ModeScreen(draft: draft),
  'Upload': () => const UploadScreen(draft: draft),
  'Results (certified)': () =>
      ResultsScreen(draft: draft, result: result(certified: true), images: List.filled(5, png)),
  'Results (missing shots)': () =>
      ResultsScreen(draft: draft, result: result(certified: false), images: List.filled(5, png)),
  'Making video (error state)': () => MakingVideoScreen(
      draft: draft, set: [SetPhoto(bytes: png, role: 'hero_shot', fqs: 0.8)]),
  'My shop': () => const BusinessProfileScreen(),
  'Set up your shop (first run)': () => const BusinessProfileScreen(firstRun: true),
  'Create account': () => AuthScreen(auth: AuthService(store: MemorySecureStore()), onDone: (_) {}),
  'Profile': () => ProfileScreen(auth: AuthService(store: MemorySecureStore())),
  'Privacy': () => const PrivacyScreen(),
  'Onboarding': () => const OnboardingScreen(),
  'Study start': () => const StudyStartScreen(),
  'Own picks': () => OwnPicksScreen(photos: List.filled(5, png)),
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    // The music preview player is a plugin; answer its calls with nothing.
    for (final ch in ['xyz.luan/audioplayers', 'xyz.luan/audioplayers.global']) {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(MethodChannel(ch), (_) async => null);
    }
  });

  for (final entry in screens.entries) {
    testWidgets('${entry.key}: 1.3x text, 48 dp targets, labels, contrast',
        (tester) async {
      tester.view.physicalSize = const Size(720, 1480); // J6+: 360 x 740 dp
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.reset);
      final semantics = tester.ensureSemantics();

      await tester.pumpWidget(MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(1.3)),
          child: child!,
        ),
        home: entry.value(),
      ));
      // Let network calls fail (tests have no network) and timers run; spinners
      // never settle, so pump a fixed time rather than pumpAndSettle.
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 200));
      }

      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      semantics.dispose();
    });
  }
}

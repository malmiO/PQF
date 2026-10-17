// Renders the v1.5.0 screens to PNG files with real fonts (Roboto and the Material
// icon font from the Flutter SDK), because no emulator is available. Skipped unless
// PQF_SHOTS names an output folder:
//   PQF_SHOTS=<dir> PQF_FONTS=<flutter>/bin/cache/artifacts/material_fonts flutter test test/screenshots_v150_test.dart
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/screens/auth_screen.dart';
import 'package:mobile/screens/business_profile_screen.dart';
import 'package:mobile/screens/home_screen.dart';
import 'package:mobile/screens/onboarding_screen.dart';
import 'package:mobile/screens/profile_screen.dart';
import 'package:mobile/services/auth_service.dart';
import 'package:mobile/services/pqf_api.dart';
import 'package:mobile/widgets/guidance_overlay.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _load(String family, List<String> files) async {
  final l = FontLoader(family);
  for (final f in files) {
    l.addFont(Future.value(ByteData.sublistView(File(f).readAsBytesSync())));
  }
  await l.load();
}

void main() {
  final out = Platform.environment['PQF_SHOTS'];
  final fonts = Platform.environment['PQF_FONTS'] ?? '';
  final key = GlobalKey();

  Future<void> shot(WidgetTester t, String name) async {
    await t.runAsync(() async {
      final b = key.currentContext!.findRenderObject() as RenderRepaintBoundary;
      final img = await b.toImage(pixelRatio: 2.0);
      final bytes = await img.toByteData(format: ui.ImageByteFormat.png);
      File('$out/$name.png')
        ..createSync(recursive: true)
        ..writeAsBytesSync(bytes!.buffer.asUint8List());
    });
  }

  Future<void> pump(WidgetTester t, Widget w) async {
    t.view.physicalSize = const Size(720, 1480); // 360 x 740 dp
    t.view.devicePixelRatio = 2.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(RepaintBoundary(
        key: key,
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: ThemeData(
              useMaterial3: true,
              fontFamily: 'Roboto',
              colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1F3A63))),
          home: w,
        )));
    await t.pump(const Duration(milliseconds: 400));
  }

  setUpAll(() async {
    if (out == null) return;
    TestWidgetsFlutterBinding.ensureInitialized();
    await _load('Roboto', ['$fonts/roboto-regular.ttf', '$fonts/roboto-bold.ttf'].where((f) => File(f).existsSync()).toList());
    await _load('MaterialIcons', ['$fonts/materialicons-regular.otf']);
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));
  final skip = out == null ? 'set PQF_SHOTS to render screenshots' : false;

  testWidgets('onboarding pages', (t) async {
    await pump(t, const OnboardingScreen(firstRun: true));
    await shot(t, '1_intro_1_what_is_eclat');
    await t.tap(find.text('Next'));
    await t.pumpAndSettle();
    await shot(t, '2_intro_2_how_it_works');
    await t.tap(find.text('Next'));
    await t.pumpAndSettle();
    await shot(t, '3_intro_3_best_setup');
  }, skip: skip != false);

  testWidgets('account and shop', (t) async {
    final auth = AuthService(store: MemorySecureStore());
    await pump(t, AuthScreen(auth: auth, onDone: (_) {}));
    await shot(t, '4_create_account');
    await pump(t, const BusinessProfileScreen(firstRun: true));
    await shot(t, '5_shop_setup');
    await auth.createAccount('Malmi', 'malmi@example.com', 'abcdef');
    await pump(t, ProfileScreen(auth: auth));
    await t.pump(const Duration(milliseconds: 400));
    await shot(t, '6_profile');
  }, skip: skip != false);

  testWidgets('home (server not reachable in a test, so the cards are greyed)', (t) async {
    await pump(t, const HomeScreen());
    await shot(t, '7_home');
  }, skip: skip != false);

  testWidgets('camera guidance widgets', (t) async {
    final g = GuidanceResult(
      ready: false,
      checks: [
        CriterionResult(name: 'framing', score: 0.3, weight: 1, passed: false),
        CriterionResult(name: 'sharpness', score: 0.9, weight: 1, passed: true),
        CriterionResult(name: 'exposure', score: 0.8, weight: 1, passed: true),
        CriterionResult(name: 'background', score: 0.9, weight: 1, passed: true),
      ],
      feedback: ['Move closer so the product fills the box.'],
      elapsedMs: 100,
    );
    await pump(
        t,
        Scaffold(
          backgroundColor: const Color(0xFF3B4250),
          body: SafeArea(
            child: Column(children: [
              const SizedBox(height: 56),
              GuidanceOverlay(guidance: g),
              const SizedBox(height: 6),
              GuidanceStatusRow(guidance: g),
            ]),
          ),
        ));
    await shot(t, '8_camera_top_chip_and_status');
    await t.pump(const Duration(seconds: 4));
    await shot(t, '9_camera_chip_collapsed_after_3s');
  }, skip: skip != false);
}

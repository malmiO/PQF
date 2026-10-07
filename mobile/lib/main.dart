import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'config/api_config.dart';
import 'screens/home_screen.dart';
import 'screens/onboarding_screen.dart';
import 'screens/privacy_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Load configuration before anything reads it. A missing file is tolerated,
  // because ApiConfig falls back to a default and the home screen will then
  // show a clear connection error rather than crashing on startup.
  try {
    await dotenv.load(fileName: 'assets/config.env');
    ApiConfig.loaded = true;
  } catch (e) {
    // Not fatal. ApiConfig falls back to defaults and the home screen shows a
    // clear connection error, which is far more useful than a crash.
    ApiConfig.loaded = false;
    debugPrint('Could not load .env ($e). Using built in defaults.');
  }
  // Show the first-run guide only until it has been seen once.
  final onboardingSeen = await OnboardingScreen.seen();
  // The privacy notice follows the introduction once; people who saw the
  // introduction before v1.1.0 get the notice on their next launch.
  final privacySeen = await PrivacyScreen.seen();
  runApp(PqfApp(showOnboarding: !onboardingSeen, showPrivacy: !privacySeen));
}

class PqfApp extends StatelessWidget {
  final bool showOnboarding;
  final bool showPrivacy;

  const PqfApp({super.key, this.showOnboarding = false, this.showPrivacy = false});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Product Photo Assistant',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1F3A63),
          brightness: Brightness.light,
        ),
        // NOTE. Do not set minimumSize here. Size.fromHeight is shorthand for
        // infinite width, which is fine inside a stretched Column but is an
        // illegal constraint inside a Row, and it crashes layout wherever a
        // button sits in a row. Height is set per button instead.
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14)),
            textStyle:
                const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
        ),
      ),
      routes: {
        '/home': (_) => const HomeScreen(),
        '/privacy': (_) => const PrivacyScreen(firstRun: true),
      },
      home: showOnboarding
          ? const OnboardingScreen(firstRun: true)
          : showPrivacy
              ? const PrivacyScreen(firstRun: true)
              : const HomeScreen(),
    );
  }
}

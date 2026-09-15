import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'config/api_config.dart';
import 'screens/home_screen.dart';

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
  runApp(const PqfApp());
}

class PqfApp extends StatelessWidget {
  const PqfApp({super.key});

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
      home: const HomeScreen(),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// First-run guide: three short screens that set expectations before the camera.
///
/// Shown once on first launch (remembered with shared_preferences) and reachable
/// again from "How it works" on the home screen. Kept to three screens, because
/// a seller came to photograph a product, not to read a manual.
class OnboardingScreen extends StatefulWidget {
  /// True on first launch: finishing replaces this with the home screen. When
  /// opened later from "How it works", it simply pops.
  final bool firstRun;

  const OnboardingScreen({super.key, this.firstRun = false});

  static const String _seenKey = 'onboarding_seen_v1';

  /// Whether the guide has already been shown. Defaults to false (show it) if
  /// preferences cannot be read, so a first run is never silently skipped.
  static Future<bool> seen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(_seenKey) ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<void> markSeen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_seenKey, true);
    } catch (_) {
      // Non-fatal: the guide shows again next launch, which is harmless.
    }
  }

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _pageController = PageController();
  int _page = 0;

  static const _pages = <_OnboardPage>[
    _OnboardPage(
      icon: Icons.photo_camera_outlined,
      title: 'What PQF does',
      body: 'Take product photos that sell, and get a ready video.',
    ),
    _OnboardPage(
      icon: Icons.light_mode_outlined,
      title: 'What you need',
      body: 'A light box, or a white sheet near a window. A phone stand if you '
          'have one.',
    ),
    _OnboardPage(
      icon: Icons.route_outlined,
      title: 'How it works',
      body: 'Product details, then photos. We check them and choose your set. '
          'Then you get your video.',
    ),
  ];

  Future<void> _finish() async {
    await OnboardingScreen.markSeen();
    if (!mounted) return;
    if (widget.firstRun) {
      // Replace with the home screen so Back does not return to the guide.
      Navigator.of(context).pushReplacementNamed('/home');
    } else {
      Navigator.of(context).pop();
    }
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final last = _page == _pages.length - 1;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.topRight,
              child: TextButton(
                onPressed: _finish,
                child: Text(widget.firstRun ? 'Skip' : 'Close'),
              ),
            ),
            Expanded(
              child: PageView.builder(
                controller: _pageController,
                itemCount: _pages.length,
                onPageChanged: (i) => setState(() => _page = i),
                itemBuilder: (_, i) => _pages[i],
              ),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(
                _pages.length,
                (i) => Container(
                  width: 9,
                  height: 9,
                  margin: const EdgeInsets.symmetric(horizontal: 4),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: i == _page
                        ? Theme.of(context).colorScheme.primary
                        : Colors.grey.shade400,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: FilledButton(
                style:
                    FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                onPressed: () {
                  if (last) {
                    _finish();
                  } else {
                    _pageController.nextPage(
                      duration: const Duration(milliseconds: 250),
                      curve: Curves.easeOut,
                    );
                  }
                },
                child: Text(last
                    ? (widget.firstRun ? 'Get started' : 'Done')
                    : 'Next'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OnboardPage extends StatelessWidget {
  final IconData icon;
  final String title;
  final String body;

  const _OnboardPage({
    required this.icon,
    required this.title,
    required this.body,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 86, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 34),
          Text(title,
              textAlign: TextAlign.center,
              style:
                  const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
          const SizedBox(height: 16),
          Text(body,
              textAlign: TextAlign.center,
              style: TextStyle(
                  fontSize: 16, color: Colors.grey.shade700, height: 1.5)),
        ],
      ),
    );
  }
}

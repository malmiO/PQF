import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../widgets/intro_art.dart';
import 'privacy_screen.dart';

/// First-run introduction (v1.5.0): three pages with vector illustrations.
///
/// Shown once on first launch (a stored flag) and reachable again from "Help" on the
/// home screen. The v1.5.0 pages replace the v1.4 text-only ones, so the flag key is
/// new: everyone sees the new introduction once.
class OnboardingScreen extends StatefulWidget {
  /// True on first launch: finishing continues into the app. When opened later from
  /// Help, it simply pops.
  final bool firstRun;

  const OnboardingScreen({super.key, this.firstRun = false});

  static const String seenKey = 'onboarding_seen_v2';

  /// Whether the introduction has been shown. Defaults to false (show it) if
  /// preferences cannot be read, so a first run is never silently skipped.
  static Future<bool> seen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getBool(seenKey) ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<void> markSeen() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(seenKey, true);
    } catch (_) {
      // Non-fatal: the introduction shows again next launch, which is harmless.
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
      art: IntroArt.whatIs,
      title: 'Welcome to Éclat',
      body: 'Take certified product photos and get a short promo video, '
          'all from your phone.',
    ),
    _OnboardPage(
      art: IntroArt.howItWorks,
      title: 'How it works',
      body: 'Guided capture, then a quality check. We pick your best set and '
          'turn it into a video.',
    ),
    _OnboardPage(
      art: IntroArt.bestSetup,
      title: 'Set up for the best photos',
      body: 'Use a light box or a white background, a steady phone or tripod, '
          'and good light.',
    ),
  ];

  Future<void> _finish() async {
    await OnboardingScreen.markSeen();
    if (!mounted) return;
    if (widget.firstRun) {
      final privacySeen = await PrivacyScreen.seen();
      if (!mounted) return;
      Navigator.of(context).pushReplacementNamed(privacySeen ? '/home' : '/privacy');
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
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
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
                child: Text(last ? (widget.firstRun ? 'Get started' : 'Done') : 'Next'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OnboardPage extends StatelessWidget {
  final IntroArt art;
  final String title;
  final String body;

  const _OnboardPage({required this.art, required this.title, required this.body});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      // The picture shrinks on a small screen or with large text, so nothing overflows.
      final artSize = (box.maxHeight * 0.42).clamp(120.0, 250.0);
      return SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: box.maxHeight),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IntroIllustration(art: art, size: artSize),
              const SizedBox(height: 24),
              Text(title,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
              const SizedBox(height: 14),
              Text(body,
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 16, color: Colors.grey.shade700, height: 1.5)),
            ],
          ),
        ),
      );
    });
  }
}

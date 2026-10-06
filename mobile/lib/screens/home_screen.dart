import 'package:flutter/material.dart';
import '../config/api_config.dart';
import '../models/api_result.dart';
import '../services/pqf_api.dart';
import '../widgets/error_view.dart';
import '../widgets/help_sheet.dart';
import '../models/study_session.dart';
import 'onboarding_screen.dart';
import 'product_form_screen.dart';
import 'study_screens.dart';

/// Entry point. Kept deliberately short, because every screen before the camera
/// is a screen between the seller and the thing they came to do.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _api = PqfApi();
  bool? _serverUp;
  ApiFailure? _failure;
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _checkServer();
  }

  Future<void> _checkServer() async {
    setState(() => _checking = true);
    final result = await _api.health();
    if (!mounted) return;
    setState(() {
      _serverUp = result.ok;
      _failure = result.failure;
      _checking = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        // LayoutBuilder plus a scroll view means the screen survives a small
        // display, a large system font, or an on screen keyboard, none of which
        // a fixed Column with a Spacer tolerates.
        child: LayoutBuilder(
          builder: (context, constraints) {
            return SingleChildScrollView(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: IntrinsicHeight(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Align(
                          alignment: Alignment.topRight,
                          child: HelpButton(HelpTopic.home),
                        ),
                        // A long press opens study mode (PIN protected), so
                        // participants never come across it (v1.1.0).
                        GestureDetector(
                          onLongPress: () async {
                            await openStudyMode(context);
                            if (mounted) setState(() {});
                          },
                          child: const Text('Product Photo Assistant',
                              style: TextStyle(
                                  fontSize: 27, fontWeight: FontWeight.bold)),
                        ),
                        if (StudySession.current != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(
                                'Session ${StudySession.current!.participant}',
                                style: TextStyle(
                                    fontSize: 12, color: Colors.grey.shade600)),
                          ),
                        const SizedBox(height: 10),
                        Text(
                          'Take product photos that are ready to post. '
                          'The app checks each shot as you take it.',
                          style: TextStyle(
                              fontSize: 15.5,
                              color: Colors.grey.shade700,
                              height: 1.4),
                        ),
                        const SizedBox(height: 30),
                        _ServerStatus(
                          checking: _checking,
                          up: _serverUp,
                          failure: _failure,
                          onRetry: _checkServer,
                        ),
                        const Expanded(child: SizedBox(height: 24)),
                        FilledButton(
                          // Full width here specifically, rather than globally.
                          style: FilledButton.styleFrom(
                              minimumSize: const Size.fromHeight(52)),
                          onPressed: _serverUp == true
                              ? () => Navigator.of(context).push(
                                    MaterialPageRoute(
                                      builder: (_) => const ProductFormScreen(),
                                    ),
                                  )
                              : null,
                          child: const Text('New product'),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          'Tip. Use a plain white or light surface, and natural '
                          'light from a window rather than overhead lighting.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                              fontSize: 13,
                              color: Colors.grey.shade600,
                              height: 1.4),
                        ),
                        const SizedBox(height: 4),
                        TextButton.icon(
                          onPressed: () =>
                              Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => const OnboardingScreen(),
                          )),
                          icon: const Icon(Icons.help_outline, size: 18),
                          label: const Text('How it works'),
                        ),
                        const SizedBox(height: 8),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _ServerStatus extends StatelessWidget {
  final bool checking;
  final bool? up;
  final ApiFailure? failure;
  final VoidCallback onRetry;

  const _ServerStatus({
    required this.checking,
    required this.up,
    required this.failure,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    if (checking) {
      return Row(children: const [
        SizedBox(
            width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
        SizedBox(width: 12),
        Text('Connecting'),
      ]);
    }

    if (up == true) {
      return Container(
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(
          color: const Color(0xFFEAF4EC),
          borderRadius: BorderRadius.circular(11),
        ),
        child: Row(children: [
          const Icon(Icons.check_circle, color: Color(0xFF2E7D32), size: 20),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Connected and ready',
                    style: TextStyle(fontSize: 13.5)),
                const SizedBox(height: 3),
                Text(ApiConfig.displayTarget,
                    style: TextStyle(
                        fontSize: 11.5,
                        color: Colors.grey.shade600,
                        fontFamily: 'monospace')),
              ],
            ),
          ),
        ]),
      );
    }

    // Not connected. Show the classified failure, which explains what went
    // wrong and what to do, rather than a generic message.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ErrorView(
          failure: failure ??
              ApiFailure.unreachable('No detail available.'),
          onRetry: onRetry,
        ),
        const SizedBox(height: 6),
        Text('Trying to reach  ${ApiConfig.displayTarget}',
            style: TextStyle(
                fontSize: 11.5,
                color: Colors.grey.shade600,
                fontFamily: 'monospace')),
      ],
    );
  }
}

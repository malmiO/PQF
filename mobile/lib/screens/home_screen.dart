import 'package:flutter/material.dart';
import '../services/pqf_api.dart';
import '../widgets/error_view.dart';
import '../widgets/help_sheet.dart';
import '../models/study_session.dart';
import 'product_form_screen.dart';
import 'profile_screen.dart';
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

  void _start(CaptureStart start) => Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ProductFormScreen(start: start)));

  /// Opens study mode. The long press on the title
  /// come here: openStudyMode asks for the PIN, and opens nothing without it.
  Future<void> _joinStudy() async {
    await openStudyMode(context);
    if (mounted) setState(() {});
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
                        Row(
                          children: [
                            Expanded(
                              // A long press opens study mode (PIN protected). Study mode
                              // has no visible button in v1.5.0.
                              child: GestureDetector(
                                onLongPress: _joinStudy,
                                child: const Text('Éclat',
                                    style: TextStyle(
                                        fontSize: 30, fontWeight: FontWeight.bold)),
                              ),
                            ),
                            const HelpButton(HelpTopic.home),
                          ],
                        ),
                        if (StudySession.current != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child: Text(
                                'Session ${StudySession.current!.participant}',
                                style: TextStyle(
                                    fontSize: 12, color: Colors.grey.shade600)),
                          ),
                        const SizedBox(height: 6),
                        Text(
                          'What would you like to do?',
                          style: TextStyle(
                              fontSize: 16, color: Colors.grey.shade700, height: 1.4),
                        ),
                        const SizedBox(height: 18),
                        _ServerStatus(
                          checking: _checking,
                          up: _serverUp,
                          failure: _failure,
                          onRetry: _checkServer,
                        ),
                        const SizedBox(height: 18),
                        _HomeCard(
                          icon: Icons.camera_alt_outlined,
                          title: 'Guided capture',
                          subtitle: 'Take photos with live guidance, one shot at a time.',
                          accent: const Color(0xFF1F3A63),
                          onTap: _serverUp == true
                              ? () => _start(CaptureStart.guided)
                              : null,
                        ),
                        // The study compares camera conditions only.
                        if (StudySession.current == null) ...[
                          const SizedBox(height: 14),
                          _HomeCard(
                            icon: Icons.photo_library_outlined,
                            title: 'Upload & check',
                            subtitle: 'Check photos you already have and get your best set.',
                            accent: const Color(0xFF2E7D32),
                            onTap: _serverUp == true
                                ? () => _start(CaptureStart.upload)
                                : null,
                          ),
                        ],
                        const Expanded(child: SizedBox(height: 16)),
                        Row(
                          children: [
                            Expanded(
                              child: OutlinedButton.icon(
                                style: OutlinedButton.styleFrom(
                                    minimumSize: const Size.fromHeight(50)),
                                onPressed: () => Navigator.of(context).push(
                                    MaterialPageRoute(builder: (_) => const ProfileScreen())),
                                icon: const Icon(Icons.person_outline, size: 20),
                                label: const Text('Profile'),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: OutlinedButton.icon(
                                style: OutlinedButton.styleFrom(
                                    minimumSize: const Size.fromHeight(50)),
                                onPressed: () => showHelpSheet(context, HelpTopic.home),
                                icon: const Icon(Icons.help_outline, size: 20),
                                label: const Text('Help'),
                              ),
                            ),
                          ],
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

class _HomeCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Color accent;
  final VoidCallback? onTap;

  const _HomeCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.accent,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      enabled: onTap != null,
      label: '$title. $subtitle',
      excludeSemantics: true,
      child: Material(
        color: onTap == null ? Colors.grey.shade600 : accent,
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: 132),
            padding: const EdgeInsets.all(20),
            child: Row(children: [
              Icon(icon, size: 46, color: Colors.white),
              const SizedBox(width: 18),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(title,
                        style: const TextStyle(
                            fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white)),
                    const SizedBox(height: 6),
                    Text(subtitle,
                        style: const TextStyle(fontSize: 14.5, color: Colors.white, height: 1.35)),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Colors.white),
            ]),
          ),
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
                color: Colors.grey.shade700, // 4.5:1 on the tinted background
                fontFamily: 'monospace')),
      ],
    );
  }
}

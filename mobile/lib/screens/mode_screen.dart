import 'package:flutter/material.dart';
import '../models/product_draft.dart';
import '../models/study_session.dart';
import '../widgets/preflight_dialog.dart';
import '../widgets/help_sheet.dart';
import 'capture_screen.dart';
import 'upload_screen.dart';

/// Choose how to provide photos.
///
/// WHY THIS SCREEN EXISTS. The two paths serve different people. Someone about
/// to photograph a product wants to be guided while they do it. Someone who
/// already has photos on their phone wants to know which are good enough and
/// what to retake. Forcing both through one flow serves neither well.
///
/// The upload path also exercises the whole framework without involving the
/// camera at all, which makes the standard easy to demonstrate and to test.
class ModeScreen extends StatelessWidget {
  final ProductDraft draft;

  const ModeScreen({super.key, required this.draft});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(draft.name),
          actions: const [HelpButton(HelpTopic.mode)]),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(22),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 8),
              const Text('How would you like to start?',
                  style: TextStyle(fontSize: 21, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text(
                'Either way, every photo is checked against the same quality '
                'standard.',
                style: TextStyle(
                    fontSize: 14.5, color: Colors.grey.shade700, height: 1.4),
              ),
              const SizedBox(height: 26),
              _ModeCard(
                icon: Icons.camera_alt,
                title: 'Take photos with guidance',
                subtitle: 'Guided, one shot at a time',
                detail: 'The app explains each shot before you take it, then '
                    'checks the camera live and tells you what to fix. It can '
                    'take the photo for you once the shot looks right.',
                accent: const Color(0xFF1F3A63),
                onTap: () async {
                  // Setup advice belongs to the camera path. Preventing blur,
                  // clutter and poor light is far cheaper than correcting them
                  // shot by shot.
                  final ready = await PreflightDialog.show(context);
                  if (!ready || !context.mounted) return;
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => CaptureScreen(draft: draft),
                  ));
                },
              ),
              // The study compares camera conditions only (v1.1.0).
              if (StudySession.current == null) ...[
              const SizedBox(height: 16),
              _ModeCard(
                icon: Icons.photo_library_outlined,
                title: 'Use photos I already have',
                subtitle: 'Check photos from your phone',
                detail: 'Choose photos you have already taken. Each one is '
                    'scored against the standard, and you are told which are '
                    'good enough, what each is useful for, and what to retake.',
                accent: const Color(0xFF2E7D32),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => UploadScreen(draft: draft),
                )),
              ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ModeCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final String detail;
  final Color accent;
  final VoidCallback onTap;

  const _ModeCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.detail,
    required this.accent,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: accent.withOpacity(0.35), width: 1.4),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: accent.withOpacity(0.10),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: accent, size: 24),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: const TextStyle(
                            fontSize: 17, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 2),
                    Text(subtitle,
                        style: TextStyle(fontSize: 13, color: accent)),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Colors.grey),
            ]),
            const SizedBox(height: 12),
            Text(detail,
                style: TextStyle(
                    fontSize: 13.5,
                    color: Colors.grey.shade700,
                    height: 1.45)),
          ],
        ),
      ),
    );
  }
}

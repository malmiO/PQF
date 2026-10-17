import 'package:flutter/material.dart';

/// Shown once before capture begins.
///
/// WHY. The three faults that ruin a non expert product photo are a moving
/// phone, a cluttered background and poor light. All three are fixed by
/// preparation, not by technique, and all three are far cheaper to prevent than
/// to correct shot by shot. Thirty seconds of setup removes most of the work
/// the live guidance would otherwise have to do.
class PreflightDialog extends StatelessWidget {
  const PreflightDialog({super.key});

  static Future<bool> show(BuildContext context) async {
    final result = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const PreflightDialog(),
    );
    return result ?? false;
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      title: const Text('Before you start'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: const [
            _Step(
              icon: Icons.phone_android,
              title: 'Keep the phone steady',
              detail: 'Rest it on a stack of books or lean it against something. '
                  'A moving phone is the most common reason a photo comes out blurred.',
            ),
            _Step(
              icon: Icons.crop_square,
              title: 'Use a plain light surface',
              detail: 'A white sheet of paper, a plain table or a light cloth. '
                  'A busy background pulls attention away from the product.',
            ),
            _Step(
              icon: Icons.wb_sunny_outlined,
              title: 'Use daylight if you can',
              detail: 'Near a window, but not in direct sun. Overhead room lights '
                  'often make colours look wrong.',
            ),
            SizedBox(height: 6),
            Text(
              'The app checks each shot as you take it and tells you what to fix.',
              style: TextStyle(fontSize: 13.5, fontStyle: FontStyle.italic),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Go back'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('I am ready'),
        ),
      ],
    );
  }
}

class _Step extends StatelessWidget {
  final IconData icon;
  final String title;
  final String detail;

  const _Step({required this.icon, required this.title, required this.detail});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 22, color: const Color(0xFF2E5090)),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(
                        fontWeight: FontWeight.w600, fontSize: 15)),
                const SizedBox(height: 3),
                Text(detail,
                    style: const TextStyle(fontSize: 13.2, height: 1.35)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

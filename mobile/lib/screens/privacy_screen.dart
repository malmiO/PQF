import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Plain English privacy notice (v1.1.0). Shown once after the introduction and
/// re-openable from every help sheet. Wording to be verified by the researcher
/// against Sri Lanka's Personal Data Protection Act, No. 9 of 2022.
class PrivacyScreen extends StatelessWidget {
  /// First launch: "I understand" continues to the home screen.
  final bool firstRun;

  const PrivacyScreen({super.key, this.firstRun = false});

  static const String _seenKey = 'privacy_seen_v1';

  static Future<bool> seen() async {
    try {
      return (await SharedPreferences.getInstance()).getBool(_seenKey) ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<void> markSeen() async {
    try {
      await (await SharedPreferences.getInstance()).setBool(_seenKey, true);
    } catch (_) {}
  }

  static const _sections = <(IconData, String, String)>[
    (Icons.upload_outlined, 'What is sent',
        'Your product photos and the product details you type, such as the name, '
            'price and key features.'),
    (Icons.dns_outlined, 'Where it goes',
        'To our photo checking server, and to Google\'s Gemini service, which '
            'checks how each photo presents the product and finds the features '
            'you name. Google\'s terms for Gemini apply to that check.'),
    (Icons.timer_outlined, 'How long it is kept',
        'Photos sent to make your video are kept on our server for up to 3 hours, '
            'then deleted automatically. Photos sent for checking are not kept.'),
    (Icons.no_accounts_outlined, 'Nothing else is stored',
        'There is no account and no login. The server keeps nothing about you.'),
    (Icons.phone_android_outlined, 'Your results stay with you',
        'Your photo set, video, caption and results are saved only on this phone. '
            'Your shop details are also kept only on this phone.'),
    (Icons.science_outlined, 'If you take part in our study',
        'Only a participant code and the photo scores are recorded, never your '
            'name, face or contact details.'),
  ];

  Future<void> _done(BuildContext context) async {
    await markSeen();
    if (!context.mounted) return;
    if (firstRun) {
      Navigator.of(context).pushReplacementNamed('/home');
    } else {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your privacy'),
        automaticallyImplyLeading: !firstRun,
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(22, 12, 22, 12),
                children: [
                  for (final (icon, title, text) in _sections)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Icon(icon, color: accent, size: 24),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(title,
                                    style: const TextStyle(
                                        fontSize: 16, fontWeight: FontWeight.w600)),
                                const SizedBox(height: 3),
                                Text(text,
                                    style: const TextStyle(fontSize: 14.5, height: 1.4)),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  Text(
                    'We follow Sri Lanka\'s Personal Data Protection Act, '
                    'No. 9 of 2022.',
                    style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(22, 4, 22, 20),
              child: FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                onPressed: () => _done(context),
                child: Text(firstRun ? 'I understand' : 'Close'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

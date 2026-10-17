import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/api_config.dart';
import '../widgets/link_row.dart';

/// Consent notice (v2). Shown and explicitly ACCEPTED before any photo is sent,
/// stored with a version number, and shown again whenever its text version
/// changes. Re-openable (read only) from every help sheet and the About screen.
///
/// Wording to be verified by the researcher against Sri Lanka's Personal Data
/// Protection Act, No. 9 of 2022.
class PrivacyScreen extends StatelessWidget {
  /// First launch / re-consent: an explicit "I agree" is required to continue.
  /// When false the screen is a read-only review with a single "Close" button.
  final bool firstRun;

  const PrivacyScreen({super.key, this.firstRun = false});

  /// The version of the consent TEXT. Bump this whenever the wording below
  /// changes in a way the user should re-read and re-accept.
  static const int consentVersion = 2;

  static const String _versionKey = 'privacy_consent_version';

  /// True once the current [consentVersion] (or a later one) has been accepted.
  /// Any older accepted version, or none, means consent must be asked again.
  static Future<bool> consented() async {
    try {
      final v =
          (await SharedPreferences.getInstance()).getInt(_versionKey) ?? 0;
      return v >= consentVersion;
    } catch (_) {
      // If preferences cannot be read, ask for consent rather than assume it.
      return false;
    }
  }

  /// Backwards compatibility: main.dart used `seen()` for the old unversioned
  /// flag. It now maps onto the versioned consent check.
  static Future<bool> seen() => consented();

  static Future<void> _accept() async {
    try {
      await (await SharedPreferences.getInstance())
          .setInt(_versionKey, consentVersion);
    } catch (_) {}
  }

  /// Section (3): title and body depend on the Gemini tier the server uses.
  /// The paid-tier variant replaces only the data-use claim.
  static (IconData, String, String) _geminiSection() => ApiConfig.geminiTier ==
          'paid'
      ? (
          Icons.cloud_outlined,
          'Google Gemini (paid tier)',
          'Google does not use these photos to improve its products.'
        )
      : (
          Icons.cloud_outlined,
          'Google Gemini (free tier)',
          'Google may keep the photos it receives, use them to improve its '
              'products, and let human reviewers see them. Once a photo is '
              'sent, this cannot be undone.'
        );

  /// Backwards-compatible accessor used by the widget test: the section (3)
  /// data-use sentence for the current tier.
  static String geminiSentence() => _geminiSection().$3;

  /// The consent sections in order. Section (3) is the tier-dependent Gemini
  /// disclosure built by [_geminiSection].
  static List<(IconData, String, String)> sections() => [
        (
          Icons.upload_outlined,
          'What is sent, and where',
          'Your product photos and the product details you type (name, price, '
              'key features) go to the Éclat server and to Google\'s Gemini AI, '
              'which judges how well each photo presents the product.'
        ),
        (
          Icons.person_off_outlined,
          'Photograph the product only',
          'Please keep people, faces, hands, signs, phone numbers and '
              'addresses out of the frame.'
        ),
        _geminiSection(),
        (
          Icons.movie_outlined,
          'When a video is made',
          'Your shop name and contact details from My shop are sent to the '
              'Éclat server and appear in the finished video.'
        ),
        (
          Icons.timer_outlined,
          'How long our server keeps them',
          'Photos and details sent to make a video are deleted from our server '
              'automatically within 3 hours. Photos sent only for checking are '
              'not stored on our server.'
        ),
        (
          Icons.no_accounts_outlined,
          'No accounts',
          'There is no account and no login. Your photo set, video, caption, '
              'results and shop details are saved only on this phone.'
        ),
        (
          Icons.science_outlined,
          'If you take part in the research study',
          'Your photos and scores are kept under a participant code, never '
              'your name, and are deleted after the project\'s assessment. The '
              'paper consent form you sign explains this in full.'
        ),
      ];

  Future<void> _agree(BuildContext context) async {
    await _accept();
    if (!context.mounted) return;
    Navigator.of(context).pushReplacementNamed('/home');
  }

  Future<void> _notNow() async {
    // Backing out is not consent. Leave the app rather than continue.
    await SystemNavigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    final privacyUrl = ApiConfig.privacyUrl;
    // On first run the user must choose; the system back gesture must not slip
    // past the consent gate.
    return PopScope(
      canPop: !firstRun,
      child: Scaffold(
        appBar: AppBar(
          title: Text(firstRun ? 'Before you start' : 'Your privacy'),
          automaticallyImplyLeading: !firstRun,
        ),
        body: SafeArea(
          child: Column(
            children: [
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(22, 14, 22, 12),
                  children: [
                    if (firstRun) ...[
                      const Text(
                        'Please read how your photos and details are used, then '
                        'tap "I agree" to continue.',
                        style: TextStyle(fontSize: 15, height: 1.4),
                      ),
                      const SizedBox(height: 18),
                    ],
                    for (final (icon, title, text) in sections())
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
                                          fontSize: 16,
                                          fontWeight: FontWeight.w600)),
                                  const SizedBox(height: 3),
                                  Text(text,
                                      style: const TextStyle(
                                          fontSize: 14.5, height: 1.4)),
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
                    if (privacyUrl != null && privacyUrl.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      LinkRow(
                        label: 'Read the full privacy policy',
                        url: privacyUrl,
                      ),
                    ],
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(22, 4, 22, 20),
                child: firstRun
                    ? Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          FilledButton(
                            style: FilledButton.styleFrom(
                                minimumSize: const Size.fromHeight(52)),
                            onPressed: () => _agree(context),
                            child: const Text('I agree'),
                          ),
                          const SizedBox(height: 8),
                          TextButton(
                            onPressed: _notNow,
                            child: const Text('Not now'),
                          ),
                        ],
                      )
                    : FilledButton(
                        style: FilledButton.styleFrom(
                            minimumSize: const Size.fromHeight(52)),
                        onPressed: () => Navigator.of(context).pop(),
                        child: const Text('Close'),
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

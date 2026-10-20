import 'package:flutter/material.dart';

import '../app_info.dart';
import '../services/pqf_api.dart';
import '../widgets/link_row.dart';
import 'privacy_screen.dart';

/// About: app and server versions, the research attribution, links, and the
/// open-source licences.
class AboutScreen extends StatefulWidget {
  const AboutScreen({super.key});

  @override
  State<AboutScreen> createState() => _AboutScreenState();
}

class _AboutScreenState extends State<AboutScreen> {
  final PqfApi _api = PqfApi();
  HealthInfo? _health;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await _api.healthInfo();
    if (!mounted) return;
    setState(() {
      if (r.ok) _health = r.value;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final website = ApiConfig.websiteUrl;
    final privacy = ApiConfig.privacyUrl;
    final feedback = ApiConfig.feedbackUrl;
    return Scaffold(
      appBar: AppBar(title: const Text('About')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(22, 18, 22, 24),
          children: [
            const Text(AppInfo.name,
                style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Text(AppInfo.tagline,
                style: TextStyle(
                    fontSize: 15,
                    fontStyle: FontStyle.italic,
                    color: Colors.grey.shade800)),
            const SizedBox(height: 10),
            Text('App ${AppInfo.version} (build ${AppInfo.build})',
                style: TextStyle(fontSize: 14, color: Colors.grey.shade700)),
            const SizedBox(height: 4),
            _ServerVersion(loading: _loading, health: _health),
            const SizedBox(height: 22),
            Text(
              AppInfo.attribution,
              style: const TextStyle(fontSize: 14.5, height: 1.45),
            ),
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 8),
            const Text('Links',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            if (website != null && website.isNotEmpty)
              LinkRow(label: 'Website', url: website, icon: Icons.public),
            if (feedback != null && feedback.isNotEmpty)
              LinkRow(
                  label: 'Feedback form',
                  url: feedback,
                  icon: Icons.feedback_outlined),
            if (privacy != null && privacy.isNotEmpty)
              LinkRow(
                  label: 'Privacy policy (web)',
                  url: privacy,
                  icon: Icons.policy_outlined),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.privacy_tip_outlined),
              title: const Text('Your privacy (in app)'),
              onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const PrivacyScreen())),
            ),
          ],
        ),
      ),
    );
  }
}

class _ServerVersion extends StatelessWidget {
  final bool loading;
  final HealthInfo? health;

  const _ServerVersion({required this.loading, required this.health});

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(fontSize: 14, color: Colors.grey.shade700);
    if (loading) {
      return Row(children: [
        const SizedBox(
            width: 13,
            height: 13,
            child: CircularProgressIndicator(strokeWidth: 2)),
        const SizedBox(width: 10),
        Text('Checking server…', style: style),
      ]);
    }
    final h = health;
    if (h == null) {
      return Text('Server version unavailable (not connected).', style: style);
    }
    return Text('Server release ${h.release}, framework ${h.frameworkVersion}',
        style: style);
  }
}

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// A tappable link that copies its URL to the clipboard.
///
/// The app deliberately does not bundle a browser-launcher dependency, so links
/// (website, privacy policy, feedback form) are copied to the clipboard and the
/// user pastes them into their browser. The full URL is shown underneath so it
/// is visible even without tapping.
class LinkRow extends StatelessWidget {
  final String label;
  final String url;
  final IconData icon;

  const LinkRow({
    super.key,
    required this.label,
    required this.url,
    this.icon = Icons.link,
  });

  Future<void> _copy(BuildContext context) async {
    await Clipboard.setData(ClipboardData(text: url));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Link copied: $url')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return InkWell(
      onTap: () => _copy(context),
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 20, color: accent),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label,
                      style: TextStyle(
                          fontSize: 15,
                          color: accent,
                          fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text(url,
                      style: TextStyle(
                          fontSize: 12.5,
                          color: Colors.grey.shade600,
                          fontFamily: 'monospace')),
                ],
              ),
            ),
            const Icon(Icons.copy, size: 16, color: Colors.grey),
          ],
        ),
      ),
    );
  }
}

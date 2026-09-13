import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../services/pqf_api.dart';

/// Results of scoring a capture batch.
///
/// DESIGN INTENT. The outcome is either a certified set or a specific thing to
/// fix. It is never a bare score, because a seller cannot act on a number. When
/// the set fails the gate, the instruction naming what is missing is the most
/// important element on the screen and is placed first.
class ResultsScreen extends StatelessWidget {
  final String productName;
  final BatchResult result;
  final List<Uint8List> images;

  const ResultsScreen({
    super.key,
    required this.productName,
    required this.result,
    required this.images,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(productName)),
      body: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          _Verdict(result: result),
          const SizedBox(height: 22),
          if (result.selected.isNotEmpty) ...[
            const Text('Your images',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(
              'Each image is labelled by how you can use it.',
              style: TextStyle(color: Colors.grey.shade700, fontSize: 13.5),
            ),
            const SizedBox(height: 14),
            ...result.selected.map((s) => _ImageCard(
                  result: s,
                  bytes: (s.index >= 0 && s.index < images.length)
                      ? images[s.index]
                      : null,
                )),
          ],
          const SizedBox(height: 18),
          if (result.certified)
            FilledButton.icon(
              onPressed: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Saving is not built yet.')),
                );
              },
              icon: const Icon(Icons.download),
              label: const Text('Save these images'),
            )
          else
            FilledButton.icon(
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.camera_alt),
              label: const Text('Take more photos'),
            ),
          const SizedBox(height: 10),
          TextButton(
            onPressed: () => Navigator.of(context)
                .popUntil((route) => route.isFirst),
            child: const Text('Start over'),
          ),
        ],
      ),
    );
  }
}

class _Verdict extends StatelessWidget {
  final BatchResult result;

  const _Verdict({required this.result});

  @override
  Widget build(BuildContext context) {
    final ok = result.certified;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: ok ? const Color(0xFFEAF4EC) : const Color(0xFFFFF6E5),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: ok ? const Color(0xFF2E7D32) : const Color(0xFFB8860B),
          width: 1.4,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(ok ? Icons.verified : Icons.info_outline,
                color: ok ? const Color(0xFF2E7D32) : const Color(0xFFB8860B)),
            const SizedBox(width: 10),
            Text(
              ok ? 'Your set is ready' : 'Almost there',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
          ]),
          const SizedBox(height: 10),
          Text(
            ok
                ? 'These photos meet the quality standard and cover the views a '
                  'customer needs.'
                : result.recaptureInstruction,
            style: const TextStyle(fontSize: 15, height: 1.4),
          ),
        ],
      ),
    );
  }
}

class _ImageCard extends StatelessWidget {
  final BatchImageResult result;
  final Uint8List? bytes;

  const _ImageCard({required this.result, required this.bytes});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Row(children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: bytes == null
                ? Container(width: 74, height: 74, color: Colors.grey.shade300)
                : Image.memory(bytes!,
                    width: 74, height: 74, fit: BoxFit.cover),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(result.roleLabel,
                    style: const TextStyle(
                        fontSize: 15.5, fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
                Text(
                  _describe(result.role),
                  style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
                ),
              ],
            ),
          ),
        ]),
      ),
    );
  }

  /// What the role means in the seller's terms, not the framework's.
  static String _describe(String role) {
    switch (role) {
      case 'hero_shot':
        return 'Use this as your main listing photo';
      case 'angle_shot':
        return 'Shows another view for customers';
      case 'detail_shot':
        return 'Close up of texture or detail';
      default:
        return 'Not used in the set';
    }
  }
}

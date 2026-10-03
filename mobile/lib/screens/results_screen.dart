import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../services/pqf_api.dart';
import '../services/image_saver.dart';

/// Results of scoring a capture batch.
///
/// DESIGN INTENT. The outcome is either a certified set or a specific thing to
/// fix. It is never a bare score, because a seller cannot act on a number. When
/// the set fails the gate, the instruction naming what is missing is the most
/// important element on the screen and is placed first.
class ResultsScreen extends StatefulWidget {
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
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  bool _saving = false;
  SaveOutcome? _outcome;

  Future<void> _save() async {
    setState(() => _saving = true);
    final outcome = await ImageSaver.save(
      productName: widget.productName,
      result: widget.result,
      images: widget.images,
    );
    if (!mounted) return;
    setState(() {
      _saving = false;
      _outcome = outcome;
    });
  }

  @override
  Widget build(BuildContext context) {
    final productName = widget.productName;
    final result = widget.result;
    final images = widget.images;
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
          if (_outcome != null) _SaveOutcomeCard(outcome: _outcome!),
          if (_outcome != null) const SizedBox(height: 12),
          if (result.selected.any((s) => s.passed))
            FilledButton.icon(
              style: FilledButton.styleFrom(
                  minimumSize: const Size.fromHeight(50)),
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.save_alt),
              label: Text(_saving
                  ? 'Saving'
                  : _outcome != null
                      ? 'Save again'
                      : 'Save these photos to my phone'),
            ),
          if (!result.certified) const SizedBox(height: 10),
          if (!result.certified)
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

/// Reports what happened when the set was saved.
///
/// Says where the files went and, honestly, how many were left out. A seller who
/// is not told that two photos were excluded will assume all of them were saved
/// and wonder later why only three are in their gallery.
class _SaveOutcomeCard extends StatelessWidget {
  final SaveOutcome outcome;

  const _SaveOutcomeCard({required this.outcome});

  @override
  Widget build(BuildContext context) {
    final ok = outcome.ok;
    return Container(
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: ok ? const Color(0xFFEAF4EC) : const Color(0xFFFDECEA),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: ok ? const Color(0xFF2E7D32) : const Color(0xFFC62828),
          width: 1.2,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(
              ok
                  ? (outcome.method == ImageSaver.methodShare
                      ? Icons.ios_share
                      : Icons.check_circle)
                  : Icons.error_outline,
              color: ok ? const Color(0xFF2E7D32) : const Color(0xFFC62828),
              size: 20,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(outcome.message,
                  style: const TextStyle(fontSize: 14.2, height: 1.4)),
            ),
          ]),
          if (outcome.note != null) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.only(left: 30),
              child: Text(outcome.note!,
                  style: TextStyle(
                      fontSize: 12.5,
                      color: Colors.grey.shade700,
                      height: 1.35)),
            ),
          ],
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
                Row(children: [
                  Icon(
                    result.passed ? Icons.check_circle : Icons.remove_circle_outline,
                    size: 16,
                    color: result.passed
                        ? const Color(0xFF2E7D32)
                        : Colors.grey.shade500,
                  ),
                  const SizedBox(width: 6),
                  Text(result.passed ? result.roleLabel : 'Not used',
                      style: const TextStyle(
                          fontSize: 15.5, fontWeight: FontWeight.w600)),
                ]),
                const SizedBox(height: 4),
                Text(
                  result.improvement ?? _describe(result.role),
                  style: TextStyle(
                      fontSize: 13,
                      color: result.passed
                          ? Colors.grey.shade700
                          : const Color(0xFF8A4F1E),
                      height: 1.3),
                ),
                const SizedBox(height: 5),
                // Scores are shown small and last. A seller does not act on
                // numbers, but during testing and for anyone who wants to
                // understand the verdict, hiding them entirely is unhelpful.
                Text(
                  'quality ${(result.tqs * 100).round()}   '
                  'presentation ${(result.sqs * 100).round()}   '
                  'overall ${(result.fqs * 100).round()}',
                  style: TextStyle(
                      fontSize: 10.5,
                      color: Colors.grey.shade500,
                      fontFamily: 'monospace'),
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

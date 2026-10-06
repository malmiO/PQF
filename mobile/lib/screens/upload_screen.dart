import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../models/api_result.dart';
import '../services/pqf_api.dart';
import '../widgets/error_view.dart';
import '../widgets/help_sheet.dart';
import 'results_screen.dart';

/// Scores photos the user already has.
///
/// This path exercises the entire framework, meaning every criterion, the
/// combination, the role classifier and the set level quality gate, without the
/// camera being involved at all. That makes the standard easy to demonstrate,
/// easy to test, and useful to a seller who has already taken photos and wants
/// to know which ones are good enough.
class UploadScreen extends StatefulWidget {
  final ProductDraft draft;

  const UploadScreen({super.key, required this.draft});

  @override
  State<UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends State<UploadScreen> {
  final PqfApi _api = PqfApi();
  final ImagePicker _picker = ImagePicker();

  final List<Uint8List> _images = [];
  final List<String> _names = [];
  bool _scoring = false;
  ApiFailure? _failure;

  /// The gate expects a workable set. More than this and the batch becomes slow
  /// and expensive, since each image costs one call to the semantic model.
  static const int maxImages = 8;

  Future<void> _pick() async {
    try {
      // NO imageQuality here, deliberately.
      //
      // Passing a quality value forces image_picker to re-encode the file. For
      // a photograph that is already JPEG, that is a second lossy compression,
      // which measurably lowers sharpness and localised distortion scores. On
      // images sitting near a role threshold it was enough to push them below
      // it, so photographs that scored as hero shots when read directly were
      // classified as angle shots by the app. Sending the original bytes means
      // the framework scores what the user actually has.
      final picked = await _picker.pickMultiImage();
      if (picked.isEmpty) return;

      final remaining = maxImages - _images.length;
      final take = picked.take(remaining).toList();

      for (final x in take) {
        final bytes = await x.readAsBytes();
        _images.add(bytes);
        _names.add(x.name);
      }
      if (!mounted) return;
      setState(() => _failure = null);

      if (picked.length > remaining) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Only the first $remaining were added. '
              'The limit is $maxImages photos.'),
        ));
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _failure = ApiFailure(
            kind: FailureKind.unknown,
            message: 'Could not open your photos.',
            action: 'Check that the app has permission to access photos.',
            technical: e.toString(),
          ));
    }
  }

  Future<void> _score() async {
    if (_images.length < 2) return;
    setState(() {
      _scoring = true;
      _failure = null;
    });

    final result = await _api.batch(_images);
    if (!mounted) return;
    setState(() => _scoring = false);

    if (!result.ok) {
      setState(() => _failure = result.failure);
      return;
    }

    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => ResultsScreen(
        draft: widget.draft,
        result: result.value!,
        images: List<Uint8List>.of(_images),
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final enough = _images.length >= 2;

    return Scaffold(
      appBar: AppBar(title: Text(widget.draft.name),
          actions: const [HelpButton(HelpTopic.upload)]),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: _images.isEmpty
                  ? _EmptyState(onPick: _pick)
                  : GridView.builder(
                      padding: const EdgeInsets.all(14),
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: 3,
                        crossAxisSpacing: 9,
                        mainAxisSpacing: 9,
                      ),
                      itemCount: _images.length +
                          (_images.length < maxImages ? 1 : 0),
                      itemBuilder: (context, i) {
                        if (i == _images.length) {
                          return _AddTile(onTap: _pick);
                        }
                        return _Thumb(
                          bytes: _images[i],
                          onRemove: _scoring
                              ? null
                              : () => setState(() {
                                    _images.removeAt(i);
                                    _names.removeAt(i);
                                  }),
                        );
                      },
                    ),
            ),
            if (_failure != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
                child: ErrorView(
                  failure: _failure!,
                  onRetry: _score,
                  onDismiss: () => setState(() => _failure = null),
                ),
              ),
            Container(
              padding: const EdgeInsets.fromLTRB(18, 12, 18, 16),
              decoration: BoxDecoration(
                color: Colors.white,
                boxShadow: [
                  BoxShadow(
                      color: Colors.black.withOpacity(0.06),
                      blurRadius: 10,
                      offset: const Offset(0, -2)),
                ],
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    _images.isEmpty
                        ? 'Choose at least two photos'
                        : enough
                            ? '${_images.length} photos ready to check'
                            : 'Add one more photo',
                    style: TextStyle(
                        fontSize: 13.5, color: Colors.grey.shade700),
                  ),
                  const SizedBox(height: 10),
                  FilledButton(
                    style: FilledButton.styleFrom(
                        minimumSize: const Size.fromHeight(50)),
                    onPressed: (enough && !_scoring) ? _score : null,
                    child: _scoring
                        ? const Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                      strokeWidth: 2, color: Colors.white)),
                              SizedBox(width: 12),
                              Text('Checking your photos'),
                            ],
                          )
                        : const Text('Check these photos'),
                  ),
                  if (_scoring) ...[
                    const SizedBox(height: 8),
                    Text('This takes a few seconds per photo',
                        style: TextStyle(
                            fontSize: 12, color: Colors.grey.shade600)),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final VoidCallback onPick;

  const _EmptyState({required this.onPick});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(30),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.photo_library_outlined,
                size: 58, color: Colors.grey.shade400),
            const SizedBox(height: 18),
            const Text('Choose photos of your product',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
            const SizedBox(height: 10),
            Text(
              'Pick a few different views. A front view, a couple of angles, '
              'and a close up of the detail works best.',
              textAlign: TextAlign.center,
              style: TextStyle(
                  fontSize: 14, color: Colors.grey.shade700, height: 1.45),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: onPick,
              icon: const Icon(Icons.add_photo_alternate_outlined),
              label: const Text('Choose photos'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Thumb extends StatelessWidget {
  final Uint8List bytes;
  final VoidCallback? onRemove;

  const _Thumb({required this.bytes, required this.onRemove});

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Image.memory(bytes, fit: BoxFit.cover),
        ),
        Positioned(
          top: 3,
          right: 3,
          child: GestureDetector(
            onTap: onRemove,
            child: Container(
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(
                color: Colors.black.withOpacity(0.6),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.close, size: 15, color: Colors.white),
            ),
          ),
        ),
      ],
    );
  }
}

class _AddTile extends StatelessWidget {
  final VoidCallback onTap;

  const _AddTile({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: Colors.grey.shade400),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.add, color: Colors.grey.shade600, size: 26),
            const SizedBox(height: 4),
            Text('Add',
                style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
          ],
        ),
      ),
    );
  }
}

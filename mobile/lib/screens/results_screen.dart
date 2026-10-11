import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../models/shot_plan.dart';
import '../models/study_session.dart';
import '../services/study_log.dart';
import '../services/pqf_api.dart';
import '../widgets/breakdown_panel.dart';
import '../widgets/error_view.dart';
import '../widgets/help_sheet.dart';
import 'capture_screen.dart';
import 'making_video_screen.dart';

/// Step 4: the chosen set and the photos not used, each with the server's reason.
///
/// DESIGN INTENT. The outcome is either a certified set, which moves on to the
/// video by itself, or the exact shots still missing, which the camera then asks
/// for and nothing else. It is never a bare score, because a seller cannot act on
/// a number.
class ResultsScreen extends StatefulWidget {
  final ProductDraft draft;
  final BatchResult result;

  /// The photos sent to /batch, in upload order (the server's `index`).
  final List<Uint8List> images;

  const ResultsScreen({
    super.key,
    required this.draft,
    required this.result,
    required this.images,
  });

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  static const autoAdvance = Duration(milliseconds: 1500);

  final PqfApi _api = PqfApi();
  late BatchResult _result;
  late List<Uint8List> _images;

  bool _checking = false;
  ApiFailure? _failure;

  /// The criteria in force (weights and pass thresholds), read once from the server
  /// for the "Why this score" panels. Null until read, or if it cannot be read.
  CriteriaInfo? _criteria;

  /// True once a "Why this score" panel has been opened: the automatic move on to the
  /// video is paused so the breakdown can be read, and a button continues instead.
  /// Display only: it changes nothing about which photos are selected or certified.
  bool _held = false;

  /// The photos of a /batch that failed, so Try again resends the same ones.
  List<Uint8List>? _pending;
  Timer? _autoNext;

  @override
  void initState() {
    super.initState();
    _result = widget.result;
    _images = widget.images;
    _loadCriteria();
    _scheduleVideo();
  }

  Future<void> _loadCriteria() async {
    final r = await _api.criteria();
    if (mounted && r.ok) setState(() => _criteria = r.value);
  }

  void _holdForReading() {
    _autoNext?.cancel();
    if (!_held && mounted) setState(() => _held = true);
  }

  BatchImageResult? _scoresFor(BatchPhoto p) {
    for (final s in _result.selected) {
      if (s.index == p.index) return s;
    }
    return null;
  }

  @override
  void dispose() {
    _autoNext?.cancel();
    super.dispose();
  }

  /// Certified: go on to the video after a moment, with no tap.
  void _scheduleVideo() {
    _autoNext?.cancel();
    if (_result.certified) _autoNext = Timer(autoAdvance, _goToVideo);
  }

  void _goToVideo() {
    if (!mounted) return;
    final set = [
      for (final p in _result.setPhotos)
        if (p.index >= 0 && p.index < _images.length)
          SetPhoto(bytes: _images[p.index], role: p.role, fqs: p.fqs),
    ];
    // Removing every route above Home releases the bytes of the photos that
    // were not used; only the set travels on.
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(
        builder: (_) => MakingVideoScreen(draft: widget.draft, set: set),
      ),
      (route) => route.isFirst,
    );
  }

  /// Opens the guided camera for ONLY the missing shots, then checks them with
  /// the photos that already passed. Photos that failed are not resent.
  Future<void> _takeMissing() async {
    var plan = ShotPlan.forMissing(
        _result.missing.map((m) => (m.role, m.count)).toList());
    if (plan.isEmpty) {
      plan = ShotPlan.steps.take(ShotPlan.requiredCount).toList();
    }
    final captured = await Navigator.of(context).push<List<Uint8List>>(
      MaterialPageRoute(
        builder: (_) => CaptureScreen(
          draft: widget.draft,
          plan: plan,
          returnPhotos: true,
        ),
      ),
    );
    if (!mounted || captured == null || captured.isEmpty) return;
    final keep = [
      for (final p in _result.images)
        if (p.passed && p.index >= 0 && p.index < _images.length)
          _images[p.index],
    ];
    await _check([...keep, ...captured]);
  }

  Future<void> _check(List<Uint8List> photos) async {
    setState(() {
      _checking = true;
      _failure = null;
      _pending = photos;
    });
    final r = await _api.batch(photos);
    if (r.ok && StudySession.current != null) StudyLog.batchResult(photos, r.value!);
    if (!mounted) return;
    if (!r.ok) {
      setState(() {
        _checking = false;
        _failure = r.failure;
      });
      return;
    }
    setState(() {
      _checking = false;
      _pending = null;
      _images = photos;
      _result = r.value!;
      _held = false;
    });
    _scheduleVideo();
  }

  Uint8List? _bytes(BatchPhoto p) =>
      (p.index >= 0 && p.index < _images.length) ? _images[p.index] : null;

  @override
  Widget build(BuildContext context) {
    final result = _result;
    final set = result.setPhotos;
    final notUsed = result.notUsed;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.draft.name),
        actions: [
          IconButton(
            icon: const Icon(Icons.help_outline),
            tooltip: 'Help',
            onPressed: () => showHelpSheet(context, HelpTopic.results),
          ),
        ],
      ),
      body: Stack(
        children: [
          ListView(
            padding: const EdgeInsets.all(18),
            children: [
              _Verdict(result: result),
              const SizedBox(height: 22),
              if (set.isNotEmpty) ...[
                const Text('Your set',
                    style:
                        TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                ...set.map((p) => _SetCard(
                      photo: p,
                      bytes: _bytes(p),
                      breakdown: BreakdownPanel(
                        photo: p,
                        scores: _scoresFor(p),
                        criteria: _criteria,
                        onOpened: _holdForReading,
                      ),
                    )),
              ],
              if (notUsed.isNotEmpty) ...[
                const SizedBox(height: 4),
                Theme(
                  data: Theme.of(context)
                      .copyWith(dividerColor: Colors.transparent),
                  child: ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    childrenPadding: EdgeInsets.zero,
                    title: Text('Not used (${notUsed.length})',
                        style: const TextStyle(
                            fontSize: 15.5, fontWeight: FontWeight.w600)),
                    children: notUsed
                        .map((p) => _NotUsedCard(
                              photo: p,
                              bytes: _bytes(p),
                              breakdown: BreakdownPanel(
                                photo: p,
                                scores: _scoresFor(p),
                                criteria: _criteria,
                                onOpened: _holdForReading,
                              ),
                            ))
                        .toList(),
                  ),
                ),
              ],
              const SizedBox(height: 18),
              if (_failure != null) ...[
                ErrorView(
                  failure: _failure!,
                  onRetry: _pending == null ? null : () => _check(_pending!),
                  onDismiss: () => setState(() => _failure = null),
                ),
                const SizedBox(height: 12),
              ],
              if (result.certified && _held)
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(50)),
                  onPressed: _goToVideo,
                  icon: const Icon(Icons.movie_creation_outlined),
                  label: const Text('Continue to your video'),
                )
              else if (result.certified)
                const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2)),
                    SizedBox(width: 10),
                    Flexible(child: Text('Making your video next')),
                  ],
                )
              else
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(50)),
                  onPressed: _checking ? null : _takeMissing,
                  icon: const Icon(Icons.camera_alt),
                  label: const Text('Take the missing shots'),
                ),
              const SizedBox(height: 10),
              TextButton(
                onPressed: () => Navigator.of(context)
                    .popUntil((route) => route.isFirst),
                child: const Text('Start over'),
              ),
            ],
          ),
          if (_checking)
            Container(
              color: Colors.black.withValues(alpha: 0.72),
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const CircularProgressIndicator(color: Colors.white),
                    const SizedBox(height: 18),
                    const Text('Checking your photos',
                        style: TextStyle(color: Colors.white, fontSize: 16.5)),
                    const SizedBox(height: 6),
                    Text('This takes a few seconds per photo',
                        style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.75),
                            fontSize: 13)),
                  ],
                ),
              ),
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
            Flexible(
              child: Text(
                ok ? 'Your set is ready' : 'Almost there',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
            ),
          ]),
          const SizedBox(height: 10),
          if (ok)
            const Text(
              'These photos meet the quality standard and cover the views a '
              'customer needs.',
              style: TextStyle(fontSize: 15, height: 1.4),
            )
          else if (result.missing.isEmpty)
            Text(result.recaptureInstruction,
                style: const TextStyle(fontSize: 15, height: 1.4))
          else
            ...result.missing.map((m) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Padding(
                        padding: EdgeInsets.only(top: 3),
                        child: Icon(Icons.add_a_photo_outlined,
                            size: 17, color: Color(0xFF8A6100)),
                      ),
                      const SizedBox(width: 9),
                      Expanded(
                        child: Text(m.message,
                            style: const TextStyle(fontSize: 15, height: 1.4)),
                      ),
                    ],
                  ),
                )),
        ],
      ),
    );
  }
}

String _roleLabel(String role) {
  switch (role) {
    case 'hero_shot':
      return 'Main shot';
    case 'angle_shot':
      return 'Angle';
    case 'detail_shot':
      return 'Detail';
    default:
      return 'Extra';
  }
}

class _Thumb extends StatelessWidget {
  final Uint8List? bytes;

  const _Thumb(this.bytes);

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: bytes == null
            ? Container(width: 74, height: 74, color: Colors.grey.shade300)
            : Image.memory(bytes!,
                width: 74, height: 74, fit: BoxFit.cover, cacheWidth: 222),
      );
}

/// A photo in the set: its role and why it was chosen.
class _SetCard extends StatelessWidget {
  final BatchPhoto photo;
  final Uint8List? bytes;

  /// The read-only "Why this score" panel shown under the photo (display only).
  final Widget? breakdown;

  const _SetCard({required this.photo, required this.bytes, this.breakdown});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.all(10),
          child: Row(children: [
          _Thumb(bytes),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Icon(Icons.check_circle,
                      size: 16, color: Color(0xFF2E7D32)),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(_roleLabel(photo.role),
                        style: const TextStyle(
                            fontSize: 15.5, fontWeight: FontWeight.w600)),
                  ),
                  Text('Photo ${photo.index + 1}',
                      style: TextStyle(
                          fontSize: 11.5, color: Colors.grey.shade600)),
                ]),
                const SizedBox(height: 4),
                Text(photo.message,
                    style: TextStyle(
                        fontSize: 13, color: Colors.grey.shade700, height: 1.3)),
                const SizedBox(height: 5),
                Text('overall ${(photo.fqs * 100).round()}',
                    style: TextStyle(
                        fontSize: 10.5,
                        color: Colors.grey.shade700, // 4.5:1 contrast (v1.1.0)
                        fontFamily: 'monospace')),
              ],
            ),
          ),
        ]),
        ),
        if (breakdown != null) breakdown!,
      ]),
    );
  }
}

/// A photo outside the set. Never shown with a role label: it is not in the set.
class _NotUsedCard extends StatelessWidget {
  final BatchPhoto photo;
  final Uint8List? bytes;

  /// The read-only "Why this score" panel shown under the photo (display only).
  final Widget? breakdown;

  const _NotUsedCard({required this.photo, required this.bytes, this.breakdown});

  (IconData, Color, String) get _look {
    switch (photo.status) {
      case 'same_view':
        return (Icons.filter_none, const Color(0xFF5C6B7A), 'Same view');
      case 'not_needed':
        return (Icons.check_circle_outline, const Color(0xFF2E7D32),
            'Not needed');
      default:
        return (Icons.error_outline, const Color(0xFFB8860B),
            'Not good enough');
    }
  }

  @override
  Widget build(BuildContext context) {
    final (icon, colour, label) = _look;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Column(children: [
        Padding(
          padding: const EdgeInsets.all(10),
          child: Row(children: [
          _Thumb(bytes),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Icon(icon, size: 16, color: colour),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(label,
                        style: const TextStyle(
                            fontSize: 14.5, fontWeight: FontWeight.w600)),
                  ),
                  Text('Photo ${photo.index + 1}',
                      style: TextStyle(
                          fontSize: 11.5, color: Colors.grey.shade600)),
                ]),
                const SizedBox(height: 4),
                Text(photo.message,
                    style: TextStyle(
                        fontSize: 13, color: Colors.grey.shade800, height: 1.3)),
              ],
            ),
          ),
        ]),
        ),
        if (breakdown != null) breakdown!,
      ]),
    );
  }
}

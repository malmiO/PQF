import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import '../services/pqf_api.dart';
import '../widgets/error_view.dart';
import '../widgets/help_sheet.dart';
import 'video_screen.dart';

/// Step 5: plans and renders the video by itself, with no input from the owner.
///
/// Two calls: POST /video/plan (the set and the product form; the server asks
/// the model once where the features are) then POST /video/render (the MP4).
/// "Try again" repeats ONLY the step that failed: a failed render never plans
/// again, unless the server says the plan itself has expired.
class MakingVideoScreen extends StatefulWidget {
  final ProductDraft draft;

  /// The certified set, in role order, as the ORIGINAL bytes that were scored.
  final List<SetPhoto> set;

  const MakingVideoScreen({super.key, required this.draft, required this.set});

  @override
  State<MakingVideoScreen> createState() => _MakingVideoScreenState();
}

enum _Step { planning, rendering }

class _MakingVideoScreenState extends State<MakingVideoScreen> {
  final PqfApi _api = PqfApi();

  _Step _step = _Step.planning;
  VideoPlan? _plan;
  ApiFailure? _failure;

  @override
  void initState() {
    super.initState();
    _run();
  }

  Future<void> _run() async {
    setState(() => _failure = null);

    if (_plan == null) {
      setState(() => _step = _Step.planning);
      final r = await _api.videoPlan(
        images: widget.set.map((p) => p.bytes).toList(),
        roles: widget.set.map((p) => p.role).toList(),
        draft: widget.draft,
      );
      if (!mounted) return;
      if (!r.ok) {
        setState(() => _failure = r.failure);
        return;
      }
      _plan = r.value;
    }

    setState(() => _step = _Step.rendering);
    final v = await _api.renderVideo(_plan!.planId);
    if (!mounted) return;
    if (!v.ok) {
      setState(() {
        // An expired plan cannot be rendered again; plan afresh next time.
        if (v.failure!.planExpired) _plan = null;
        _failure = v.failure;
      });
      return;
    }

    // The checklist measured from the finished video is saved with the plan.
    // If it cannot be read, the plan's own checklist is shown instead.
    final measured = await _api.getVideoPlan(_plan!.planId);
    if (!mounted) return;
    if (measured.ok) _plan = measured.value;

    try {
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/pqf_promo_video.mp4';
      await File(path).writeAsBytes(v.value!.bytes, flush: true);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => VideoScreen(
          draft: widget.draft,
          set: widget.set,
          plan: _plan!,
          videoPath: path,
        ),
      ));
    } catch (e) {
      debugPrint('[video] writing the mp4 failed: $e');
      if (!mounted) return;
      setState(() =>
          _failure = ApiFailure.unknown('Could not open the finished video. $e'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final planDone = _plan != null;
    final failedPlanning = _failure != null && _step == _Step.planning;
    final failedRendering = _failure != null && _step == _Step.rendering;
    return Scaffold(
      appBar: AppBar(title: const Text('Making your video'),
          actions: const [HelpButton(HelpTopic.makingVideo)]),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(22),
          children: [
            Text(widget.draft.name,
                style:
                    const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text('${widget.set.length} photos from your set. '
                'No need to do anything; this takes about a minute.',
                style: TextStyle(fontSize: 14, color: Colors.grey.shade700)),
            const SizedBox(height: 22),
            if (_failure == null) const LinearProgressIndicator(),
            const SizedBox(height: 18),
            _StepRow(
              label: 'Planning your video',
              state: failedPlanning
                  ? _RowState.failed
                  : planDone
                      ? _RowState.done
                      : _RowState.active,
            ),
            _StepRow(
              label: 'Making the video',
              state: failedRendering
                  ? _RowState.failed
                  : _step == _Step.rendering
                      ? _RowState.active
                      : _RowState.waiting,
            ),
            if (_failure != null) ...[
              const SizedBox(height: 18),
              ErrorView(failure: _failure!, onRetry: _run),
            ],
          ],
        ),
      ),
    );
  }
}

enum _RowState { waiting, active, done, failed }

class _StepRow extends StatelessWidget {
  final String label;
  final _RowState state;

  const _StepRow({required this.label, required this.state});

  @override
  Widget build(BuildContext context) {
    final Widget lead;
    switch (state) {
      case _RowState.active:
        lead = const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2.4));
      case _RowState.done:
        lead = const Icon(Icons.check_circle, color: Color(0xFF2E7D32));
      case _RowState.failed:
        lead = const Icon(Icons.error, color: Color(0xFFC62828));
      case _RowState.waiting:
        lead = Icon(Icons.radio_button_unchecked, color: Colors.grey.shade400);
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 9),
      child: Row(children: [
        SizedBox(width: 24, child: Center(child: lead)),
        const SizedBox(width: 14),
        Text(label,
            style: TextStyle(
                fontSize: 16,
                fontWeight: state == _RowState.active
                    ? FontWeight.w600
                    : FontWeight.normal,
                color: state == _RowState.waiting
                    ? Colors.grey.shade500
                    : Colors.black87)),
      ]),
    );
  }
}

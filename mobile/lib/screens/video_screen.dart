import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:video_player/video_player.dart';

import '../services/image_saver.dart';
import '../models/study_session.dart';
import '../services/study_log.dart';
import '../widgets/help_sheet.dart';
import '../services/pqf_api.dart';

/// Step 6: the finished video, ready to post.
///
/// Plays by itself and loops. Shows the plan's "ready to post" checklist and the
/// post caption to copy. Everything (the set photos, the video, the caption and
/// results.json) is saved to the phone once, automatically, as soon as this
/// screen opens.
class VideoScreen extends StatefulWidget {
  final ProductDraft draft;

  /// The certified set, in the order it was sent to /video/plan.
  final List<SetPhoto> set;
  final VideoPlan plan;

  /// The rendered MP4 on local storage.
  final String videoPath;

  const VideoScreen({
    super.key,
    required this.draft,
    required this.set,
    required this.plan,
    required this.videoPath,
  });

  @override
  State<VideoScreen> createState() => _VideoScreenState();
}

class _VideoScreenState extends State<VideoScreen> {
  VideoPlayerController? _controller;
  String? _playerError;
  bool _muted = false;

  bool _saving = false;
  PackageSaveOutcome? _saveOutcome;

  @override
  void initState() {
    super.initState();
    _openVideo();
    // Study mode: the time the video was ready (v1.1.0).
    final study = StudySession.current;
    if (study != null && study.videoReadyAt == null) {
      study.videoReadyAt = DateTime.now().toUtc();
      StudyLog.log('video_ready');
    }
    // Save once, automatically, after the first frame (so a snackbar can show).
    WidgetsBinding.instance.addPostFrameCallback((_) => _save());
  }

  Future<void> _openVideo() async {
    final c = VideoPlayerController.file(File(widget.videoPath));
    try {
      await c.initialize();
      await c.setLooping(true);
      await c.play();
      if (!mounted) {
        await c.dispose();
        return;
      }
      setState(() => _controller = c);
    } catch (e) {
      debugPrint('[video] player failed: $e');
      await c.dispose();
      if (mounted) setState(() => _playerError = 'The video could not be played here.');
    }
  }

  Future<void> _save() async {
    if (_saving) return;
    setState(() => _saving = true);
    final outcome = await ImageSaver.saveProduct(
      draft: widget.draft,
      set: widget.set,
      videoPath: widget.videoPath,
      plan: widget.plan,
    );
    if (!mounted) return;
    setState(() {
      _saving = false;
      _saveOutcome = outcome;
    });
    if (outcome.ok) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Saved to your phone: ${outcome.folder}'),
      ));
    }
  }

  Future<void> _share() async {
    try {
      await SharePlus.instance.share(ShareParams(
          files: [XFile(widget.videoPath)],
          subject: widget.draft.name,
          text: widget.plan.caption));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not share the video.')),
        );
      }
    }
  }

  Future<void> _copyCaption() async {
    await Clipboard.setData(ClipboardData(text: widget.plan.caption));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Caption copied.')),
      );
    }
  }

  void _toggleMute() {
    final c = _controller;
    if (c == null) return;
    setState(() => _muted = !_muted);
    c.setVolume(_muted ? 0 : 1);
  }

  Future<void> _replay() async {
    final c = _controller;
    if (c == null) return;
    await c.seekTo(Duration.zero);
    await c.play();
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = _controller;
    final square = widget.draft.format == 'square';
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your video'),
        automaticallyImplyLeading: false,
        actions: const [HelpButton(HelpTopic.video)],
      ),
      body: SafeArea(
        child: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(context).size.height * 0.55),
              child: AspectRatio(
                aspectRatio: c != null && c.value.aspectRatio > 0
                    ? c.value.aspectRatio
                    : (square ? 1 : 9 / 16),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    color: Colors.black,
                    child: c != null
                        ? VideoPlayer(c)
                        : Center(
                            child: _playerError == null
                                ? const CircularProgressIndicator(
                                    color: Colors.white)
                                : Text(_playerError!,
                                    style:
                                        const TextStyle(color: Colors.white)),
                          ),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 6),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            IconButton(
              tooltip: _muted ? 'Sound on' : 'Mute',
              icon: Icon(_muted ? Icons.volume_off : Icons.volume_up),
              onPressed: c == null ? null : _toggleMute,
            ),
            const SizedBox(width: 12),
            IconButton(
              tooltip: 'Replay',
              icon: const Icon(Icons.replay),
              onPressed: c == null ? null : _replay,
            ),
          ]),
          const SizedBox(height: 6),
          _SaveStatus(saving: _saving, outcome: _saveOutcome, onSaveAgain: _save),
          const SizedBox(height: 14),
          _Card(
            title: 'Ready to post',
            child: Column(
              children: widget.plan.checklist
                  .map((item) => _ChecklistRow(item: item))
                  .toList(),
            ),
          ),
          const SizedBox(height: 14),
          _Card(
            title: 'Post caption',
            trailing: TextButton.icon(
              onPressed: _copyCaption,
              icon: const Icon(Icons.copy, size: 18),
              label: const Text('Copy'),
            ),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFF4F6F9),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: Colors.grey.shade300),
              ),
              child: SelectableText(widget.plan.caption,
                  style: const TextStyle(fontSize: 14, height: 1.45)),
            ),
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
            onPressed: _share,
            icon: const Icon(Icons.ios_share),
            label: const Text('Share video'),
          ),
          const SizedBox(height: 10),
          OutlinedButton(
            style:
                OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(50)),
            onPressed: () =>
                Navigator.of(context).popUntil((route) => route.isFirst),
            child: const Text('Done'),
          ),
        ],
      ),
      ),
    );
  }
}

class _Card extends StatelessWidget {
  final String title;
  final Widget child;
  final Widget? trailing;

  const _Card({required this.title, required this.child, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(
                child: Text(title,
                    style: const TextStyle(
                        fontSize: 16.5, fontWeight: FontWeight.bold)),
              ),
              if (trailing != null) trailing!,
            ]),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}

class _ChecklistRow extends StatelessWidget {
  final ChecklistItem item;

  const _ChecklistRow({required this.item});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 1),
            child: item.met
                ? const Icon(Icons.check_circle,
                    size: 19, color: Color(0xFF2E7D32))
                : const Padding(
                    padding: EdgeInsets.all(4.5),
                    child: CircleAvatar(
                        radius: 5, backgroundColor: Color(0xFFE0A100)),
                  ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.rule,
                    style: const TextStyle(
                        fontSize: 14.5, fontWeight: FontWeight.w600)),
                if (item.detail.isNotEmpty)
                  Text(item.detail,
                      style: TextStyle(
                          fontSize: 12.8,
                          color: Colors.grey.shade700,
                          height: 1.35)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Where the automatic save stands. On failure: the reason and "Save again".
class _SaveStatus extends StatelessWidget {
  final bool saving;
  final PackageSaveOutcome? outcome;
  final VoidCallback onSaveAgain;

  const _SaveStatus({
    required this.saving,
    required this.outcome,
    required this.onSaveAgain,
  });

  @override
  Widget build(BuildContext context) {
    if (saving) {
      return const Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2)),
          SizedBox(width: 10),
          Text('Saving to your phone'),
        ],
      );
    }
    final o = outcome;
    if (o == null) return const SizedBox.shrink();
    final ok = o.ok;
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: ok ? const Color(0xFFEAF4EC) : const Color(0xFFFDECEA),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
            color: ok ? const Color(0xFF2E7D32) : const Color(0xFFC62828)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(ok ? Icons.check_circle : Icons.error_outline,
                size: 20,
                color: ok ? const Color(0xFF2E7D32) : const Color(0xFFC62828)),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                ok
                    ? 'Saved to your phone: ${o.folder}'
                    : (o.shared
                        ? '${o.error} The share sheet was opened instead, so '
                            'nothing is in ${o.folder} yet.'
                        : o.error ?? 'Saving did not finish.'),
                style: const TextStyle(fontSize: 13.8, height: 1.35),
              ),
            ),
          ]),
          if (o.note != null) ...[
            const SizedBox(height: 6),
            Text(o.note!,
                style: TextStyle(
                    fontSize: 12.3, color: Colors.grey.shade700, height: 1.35)),
          ],
          if (!ok)
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton(
                  onPressed: onSaveAgain, child: const Text('Save again')),
            ),
        ],
      ),
    );
  }
}

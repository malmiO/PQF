import 'dart:io' show File;
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../config/api_config.dart';
import '../models/study_session.dart';
import '../services/study_data.dart';
import '../services/study_log.dart';
import '../services/study_share.dart';
import 'product_form_screen.dart';

/// Opens study mode after the PIN (PQF_STUDY_PIN in config.env). Hidden: reached
/// only by a long press on the home screen title, so participants never see it.
Future<void> openStudyMode(BuildContext context) async {
  final pin = ApiConfig.studyPin;
  if (pin == null) {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Study mode is not set up (PQF_STUDY_PIN in config.env).')));
    return;
  }
  final ok = await showDialog<bool>(
    context: context,
    builder: (_) => _PinDialog(pin: pin),
  );
  if (!context.mounted || ok == null) return;
  if (!ok) {
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('Wrong PIN.')));
    return;
  }
  Navigator.of(context)
      .push(MaterialPageRoute(builder: (_) => const StudyStartScreen()));
}

/// The PIN prompt. It owns its text controller, so the controller is disposed with the
/// dialog and not while the dialog's closing animation is still drawing the field
/// (the earlier version disposed it as soon as showDialog returned). Returns true only
/// when the typed PIN equals [pin]; Cancel and an empty field return false.
class _PinDialog extends StatefulWidget {
  final String pin;

  const _PinDialog({required this.pin});

  @override
  State<_PinDialog> createState() => _PinDialogState();
}

class _PinDialogState extends State<_PinDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Study mode'),
      content: TextField(
        controller: _controller,
        autofocus: true,
        obscureText: true,
        maxLength: 4,
        keyboardType: TextInputType.number,
        decoration: const InputDecoration(labelText: 'PIN'),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        FilledButton(
            onPressed: () => Navigator.pop(context, _controller.text == widget.pin),
            child: const Text('Open')),
      ],
    );
  }
}

/// Start of a session: participant code, product code and session number. The
/// condition comes from the counterbalanced (ABBA) order, shown on screen.
class StudyStartScreen extends StatefulWidget {
  const StudyStartScreen({super.key});

  @override
  State<StudyStartScreen> createState() => _StudyStartScreenState();
}

class _StudyStartScreenState extends State<StudyStartScreen> {
  final _participant = TextEditingController(text: 'P');
  final _product = TextEditingController();
  int _session = 1;
  String _group = StudySession.seller;

  /// Session 2 only: is this the same physical product as the first condition?
  bool? _sameProduct;

  // What study data is on this phone (photos and log), for the export card.
  ({int photos, int bytes, bool hasLog})? _data;
  bool _busy = false;

  /// The zip written by the last successful export, so it can be shared again.
  File? _lastZip;

  @override
  void initState() {
    super.initState();
    _refreshData();
  }

  @override
  void dispose() {
    _participant.dispose();
    _product.dispose();
    super.dispose();
  }

  Future<void> _refreshData() async {
    final d = await StudyData.summary();
    if (mounted) setState(() => _data = d);
  }

  void _say(String message, {int seconds = 4}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message), duration: Duration(seconds: seconds)));
  }

  /// One zip (study_log.jsonl + study/photos/...) in the app's own folder, which needs
  /// no storage permission and can be pulled with adb. The message gives the full path.
  Future<void> _export() async {
    setState(() => _busy = true);
    try {
      final r = await StudyData.export();
      if (mounted) setState(() => _lastZip = r.zip);
      _say(
          r.adbReachable
              ? 'Exported. On the laptop: adb pull "${r.zip.path}"'
              : "Exported to the app's private folder (not reachable with adb): "
                  '${r.zip.path}',
          seconds: 20);
      // Open the share sheet once, right after a successful export. The zip is already
      // written, so closing the sheet loses nothing; "Share" below opens it again.
      await _share(r.zip);
    } on StateError catch (e) {
      _say(e.message);
    } catch (e) {
      _say('Export failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
      await _refreshData();
    }
  }

  /// Opens the Android share sheet for [zip]. A failure here never undoes the export.
  Future<void> _share(File zip) async {
    try {
      await StudyShare.share(zip);
    } catch (e) {
      _say('The share sheet could not be opened: $e');
    }
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete study data?'),
        content: const Text(
            'This permanently removes the study log and every saved photo from '
            'this phone. Export first, and check the zip opens on the laptop. '
            'This cannot be undone.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      await StudyData.deleteAll();
      _say('Study data deleted from this phone.');
    } catch (e) {
      _say('Delete failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
      await _refreshData();
    }
  }

  bool get _valid =>
      StudySession.participantPattern.hasMatch(_participant.text.trim()) &&
      StudySession.productPattern.hasMatch(_product.text.trim()) &&
      (_session != 2 || _sameProduct != null);

  Future<void> _start() async {
    final s = StudySession(
      participant: _participant.text.trim(),
      product: _product.text.trim(),
      session: _session,
      group: _group,
      sameProductAsFirst: _session == 2 ? _sameProduct : null,
    );
    StudySession.current = s;
    await StudyLog.sessionStart(s);
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const ProductFormScreen()));
  }

  void _end() {
    StudySession.current = null;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final code = _participant.text.trim();
    final order = StudySession.participantPattern.hasMatch(code)
        ? StudySession.abbaOrder(code)
        : null;
    final active = StudySession.current;
    return Scaffold(
      appBar: AppBar(title: const Text('Study session')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (active != null) ...[
            Card(
              child: ListTile(
                title: Text('Running: ${active.participant}, session '
                    '${active.session}, ${active.condition}'),
                trailing: TextButton(onPressed: _end, child: const Text('End')),
              ),
            ),
            const SizedBox(height: 12),
          ],
          const Text('Codes only. Never enter a name or contact details.',
              style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 14),
          TextField(
            controller: _participant,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(
                labelText: 'Participant code', hintText: 'P01',
                border: OutlineInputBorder()),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _product,
            decoration: const InputDecoration(
                labelText: 'Product code', hintText: 'K1',
                border: OutlineInputBorder()),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 16),
          const Text('Participant group', style: TextStyle(fontSize: 14)),
          const SizedBox(height: 6),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: StudySession.seller, label: Text('Seller')),
              ButtonSegment(value: StudySession.nonExpert, label: Text('Non-expert')),
            ],
            selected: {_group},
            onSelectionChanged: (v) => setState(() => _group = v.first),
          ),
          const SizedBox(height: 18),
          if (order != null) ...[
            Text('Order for $code: 1. ${order[0]}   2. ${order[1]}',
                style: const TextStyle(fontSize: 15.5)),
            const SizedBox(height: 10),
            SegmentedButton<int>(
              segments: [
                ButtonSegment(value: 1, label: Text('Session 1: ${order[0]}')),
                ButtonSegment(value: 2, label: Text('Session 2: ${order[1]}')),
              ],
              selected: {_session},
              onSelectionChanged: (v) => setState(() {
                _session = v.first;
                if (_session != 2) _sameProduct = null;
              }),
            ),
          ],
          if (_session == 2) ...[
            const SizedBox(height: 14),
            const Text('Same product as the first condition?',
                style: TextStyle(fontSize: 15)),
            const SizedBox(height: 6),
            SegmentedButton<bool>(
              segments: const [
                ButtonSegment(value: true, label: Text('Yes')),
                ButtonSegment(value: false, label: Text('No')),
              ],
              selected: _sameProduct == null ? <bool>{} : {_sameProduct!},
              emptySelectionAllowed: true,
              onSelectionChanged: (v) =>
                  setState(() => _sameProduct = v.isEmpty ? null : v.first),
            ),
          ],
          const SizedBox(height: 24),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
            onPressed: _valid ? _start : null,
            child: const Text('Start session'),
          ),
          const SizedBox(height: 28),
          const Divider(),
          const SizedBox(height: 8),
          const Text('Study data on this phone',
              style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16)),
          const SizedBox(height: 6),
          Text(_data == null
              ? 'Checking...'
              : '${_data!.photos} photos '
                  '(${(_data!.bytes / (1024 * 1024)).toStringAsFixed(1)} MB), '
                  'log ${_data!.hasLog ? 'present' : 'none'}'),
          const SizedBox(height: 12),
          FilledButton.tonal(
            style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
            onPressed: _busy ? null : _export,
            child: const Text('Export study data'),
          ),
          if (_lastZip != null) ...[
            const SizedBox(height: 10),
            FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: _busy ? null : () => _share(_lastZip!),
              icon: const Icon(Icons.share),
              label: const Text('Share the last export'),
            ),
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(_lastZip!.uri.pathSegments.last,
                  style: const TextStyle(fontSize: 12)),
            ),
          ],
          const SizedBox(height: 10),
          OutlinedButton(
            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
            // Never while a session is running: that would delete its photos.
            onPressed: (_busy || active != null) ? null : _delete,
            child: const Text('Clear study data'),
          ),
          if (active != null)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text('End the running session before deleting.',
                  style: TextStyle(fontSize: 13)),
            ),
        ],
      ),
    );
  }
}

/// The participant chooses their own main, angle 1, angle 2 and detail BEFORE
/// the framework's results are shown. Returns slot -> photo, or null if left.
class OwnPicksScreen extends StatefulWidget {
  final List<Uint8List> photos;

  const OwnPicksScreen({super.key, required this.photos});

  @override
  State<OwnPicksScreen> createState() => _OwnPicksScreenState();
}

class _OwnPicksScreenState extends State<OwnPicksScreen> {
  static const slots = [
    ('main', 'Main'),
    ('angle1', 'Angle 1'),
    ('angle2', 'Angle 2'),
    ('detail', 'Detail'),
  ];
  final Map<String, int> _picks = {};
  String _slot = 'main';

  void _pick(int i) {
    setState(() {
      _picks.removeWhere((_, v) => v == i);   // one photo, one slot
      _picks[_slot] = i;
      final next = slots.map((s) => s.$1).where((s) => !_picks.containsKey(s));
      if (next.isNotEmpty) _slot = next.first;
    });
  }

  @override
  Widget build(BuildContext context) {
    final done = _picks.length == slots.length;
    return Scaffold(
      appBar: AppBar(title: const Text('Your choice')),
      body: Column(
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 14, 16, 6),
            child: Text(
                'Which photos would you use? Choose one for each: tap a box, '
                'then tap a photo.',
                style: TextStyle(fontSize: 15, height: 1.35)),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Wrap(
              spacing: 8,
              children: [
                for (final (key, label) in slots)
                  ChoiceChip(
                    label: Text(_picks.containsKey(key)
                        ? '$label: photo ${_picks[key]! + 1}'
                        : label),
                    selected: _slot == key,
                    onSelected: (_) => setState(() => _slot = key),
                  ),
              ],
            ),
          ),
          Expanded(
            child: GridView.builder(
              padding: const EdgeInsets.all(12),
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 3, crossAxisSpacing: 8, mainAxisSpacing: 8),
              itemCount: widget.photos.length,
              itemBuilder: (_, i) {
                final slot = _picks.entries
                    .where((e) => e.value == i)
                    .map((e) => slots.firstWhere((s) => s.$1 == e.key).$2)
                    .firstOrNull;
                return GestureDetector(
                  onTap: () => _pick(i),
                  child: Stack(fit: StackFit.expand, children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.memory(widget.photos[i],
                          fit: BoxFit.cover, cacheWidth: 300),
                    ),
                    Positioned(
                      left: 4,
                      top: 4,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        color: slot == null ? Colors.black54 : const Color(0xFF1F3A63),
                        child: Text(slot ?? 'Photo ${i + 1}',
                            style: const TextStyle(color: Colors.white, fontSize: 12)),
                      ),
                    ),
                  ]),
                );
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
            child: FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
              onPressed: done
                  ? () => Navigator.of(context).pop(
                      _picks.map((k, v) => MapEntry(k, widget.photos[v])))
                  : null,
              child: const Text('Done'),
            ),
          ),
        ],
      ),
    );
  }
}

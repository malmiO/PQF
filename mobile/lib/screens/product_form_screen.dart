import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';

import '../services/pqf_api.dart';
import '../models/business_profile.dart';
import '../widgets/help_sheet.dart';
import '../widgets/preflight_dialog.dart';
import 'capture_screen.dart';
import 'mode_screen.dart';
import 'upload_screen.dart';

/// Step 1 of a product: what it is, and how its video should look.
///
/// Everything the video needs is asked HERE, once, so the rest of the flow
/// (photos, checking, the video) runs without further questions.
/// Which capture path the owner picked on the home screen (v1.5.0). `ask` shows the
/// older "How would you like to start?" screen.
enum CaptureStart { ask, guided, upload }

class ProductFormScreen extends StatefulWidget {
  final CaptureStart start;
  const ProductFormScreen({super.key, this.start = CaptureStart.ask});

  @override
  State<ProductFormScreen> createState() => _ProductFormScreenState();
}

class _ProductFormScreenState extends State<ProductFormScreen> {
  static const categories = [
    'Accessories',
    'Jewellery',
    'Cosmetics',
    'Skincare',
    'Clothing',
    'Food',
    'Handmade',
    'Other',
  ];
  static const moods = ['calm', 'elegant', 'upbeat'];

  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _price = TextEditingController();
  final _features = List.generate(3, (_) => TextEditingController());

  final PqfApi _api = PqfApi();
  /// Created on the first preview only, so no player exists unless the owner
  /// listens (and none to release otherwise).
  AudioPlayer? _player;

  AudioPlayer get _audio {
    final existing = _player;
    if (existing != null) return existing;
    final p = AudioPlayer();
    p.onPlayerComplete.listen((_) {
      if (mounted) setState(() => _playing = false);
    });
    return _player = p;
  }

  String? _category;
  String _mood = '';
  String _format = 'vertical';

  /// Once the owner picks a mood, a category change no longer overrides it.
  bool _moodChosen = false;
  MusicRecommendation? _music;
  bool _loadingMusic = false;
  int _musicRequest = 0;
  bool _playing = false;

  @override
  void initState() {
    super.initState();
    _loadMusic();
  }

  /// GET /music for the category: the recommended mood, the mood descriptions
  /// and the installed tracks.
  Future<void> _loadMusic() async {
    final request = ++_musicRequest;
    setState(() => _loadingMusic = true);
    final r = await _api.music(_category);
    if (!mounted || request != _musicRequest) return;
    setState(() {
      _loadingMusic = false;
      if (r.ok) {
        _music = r.value;
        if (!_moodChosen && moods.contains(r.value!.recommendedMood)) {
          _mood = r.value!.recommendedMood;
        }
      }
    });
  }

  MusicTrack? get _previewTrack => _music?.firstTrack(_mood);

  Future<void> _togglePreview() async {
    final t = _previewTrack;
    if (t == null) return;
    try {
      if (_playing) {
        await _audio.stop();
        if (mounted) setState(() => _playing = false);
        return;
      }
      await _audio.play(UrlSource(_api.musicPreviewUrl(t.id)));
      if (mounted) setState(() => _playing = true);
    } catch (e) {
      debugPrint('Music preview failed. $e');
      if (mounted) {
        setState(() => _playing = false);
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Could not play the music.')));
      }
    }
  }

  Future<void> _selectMood(String m) async {
    if (_playing) await _player?.stop();
    if (!mounted) return;
    setState(() {
      _mood = m;
      _moodChosen = true;
      _playing = false;
    });
  }

  Future<void> _next() async {
    if (!_formKey.currentState!.validate()) return;
    if (_playing) await _player?.stop();
    // The shop, contact and colour from My shop go into every video (v1.1.0).
    final profile = await BusinessProfile.load();
    if (!mounted) return;
    setState(() => _playing = false);
    final draft = ProductDraft(
      name: _name.text.trim(),
      price: _price.text.trim(),
      features: _features.map((c) => c.text.trim()).toList(),
      category: _category ?? '',
      mood: _mood,
      format: _format,
      shop: profile.shop,
      contact: profile.videoContact,
      brandColour: profile.colour,
    );
    switch (widget.start) {
      case CaptureStart.guided:
        // Same setup advice as the Mode screen's guided card.
        final ready = await PreflightDialog.show(context);
        if (!ready || !mounted) return;
        Navigator.of(context)
            .push(MaterialPageRoute(builder: (_) => CaptureScreen(draft: draft)));
      case CaptureStart.upload:
        Navigator.of(context)
            .push(MaterialPageRoute(builder: (_) => UploadScreen(draft: draft)));
      case CaptureStart.ask:
        Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => ModeScreen(draft: draft),
        ));
    }
  }

  @override
  void dispose() {
    _player?.dispose();
    _name.dispose();
    _price.dispose();
    for (final c in _features) {
      c.dispose();
    }
    super.dispose();
  }

  InputDecoration _decoration(String label, {String? hint}) => InputDecoration(
        labelText: label,
        hintText: hint,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      );

  @override
  Widget build(BuildContext context) {
    final recommended = _music?.recommendedMood ?? '';
    final track = _previewTrack;
    return Scaffold(
      appBar: AppBar(title: const Text('Product details'),
          actions: const [HelpButton(HelpTopic.productForm)]),
      body: SafeArea(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
            children: [
              TextFormField(
                controller: _name,
                maxLength: 40,
                textCapitalization: TextCapitalization.words,
                decoration: _decoration('Product name'),
                validator: (v) => (v == null || v.trim().isEmpty)
                    ? 'Enter the product name.'
                    : null,
              ),
              const SizedBox(height: 6),
              TextFormField(
                controller: _price,
                maxLength: 24,
                decoration: _decoration('Price (optional)', hint: 'Rs. 450'),
              ),
              const SizedBox(height: 10),
              const _SectionTitle('Key features (optional)'),
              Text('These will be pointed out on your photo in the video.',
                  style:
                      TextStyle(fontSize: 13, color: Colors.grey.shade700)),
              const SizedBox(height: 10),
              for (var i = 0; i < _features.length; i++) ...[
                TextFormField(
                  controller: _features[i],
                  maxLength: 30,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: _decoration('Feature ${i + 1}',
                      hint: "Short, like 'Silver clasp'"),
                ),
                const SizedBox(height: 4),
              ],
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(
                initialValue: _category,
                decoration: _decoration('Category'),
                items: categories
                    .map((c) => DropdownMenuItem(value: c, child: Text(c)))
                    .toList(),
                onChanged: (c) {
                  setState(() => _category = c);
                  _loadMusic();
                },
              ),
              const SizedBox(height: 22),
              Row(children: [
                const Expanded(child: _SectionTitle('Video style')),
                if (_loadingMusic)
                  const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2)),
              ]),
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      children: [
                        for (final m in moods)
                          _MoodChip(
                            title: _title(m) +
                                (m == recommended ? ' (recommended)' : ''),
                            subtitle: _music?.moodDescriptions[m] ?? '',
                            selected: _mood == m,
                            onTap: () => _selectMood(m),
                          ),
                      ],
                    ),
                  ),
                  // Preview of the first track of the selected mood. Hidden when
                  // that mood has no track installed.
                  if (track != null)
                    Padding(
                      padding: const EdgeInsets.only(left: 6),
                      child: IconButton.filledTonal(
                        tooltip: _playing ? 'Stop' : 'Listen: ${track.title}',
                        iconSize: 30,
                        icon: Icon(_playing ? Icons.stop : Icons.play_arrow),
                        onPressed: _togglePreview,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 18),
              const _SectionTitle('Video shape'),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(
                  child: _FormatCard(
                    title: 'Vertical',
                    subtitle: 'Reels, TikTok, Shorts',
                    icon: Icons.crop_portrait,
                    selected: _format == 'vertical',
                    onTap: () => setState(() => _format = 'vertical'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _FormatCard(
                    title: 'Square',
                    subtitle: 'Feed',
                    icon: Icons.crop_square,
                    selected: _format == 'square',
                    onTap: () => setState(() => _format = 'square'),
                  ),
                ),
              ]),
              const SizedBox(height: 26),
              FilledButton(
                style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(52)),
                onPressed: _next,
                child: const Text('Next'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _title(String mood) =>
      mood.isEmpty ? mood : mood[0].toUpperCase() + mood.substring(1);
}

class _SectionTitle extends StatelessWidget {
  final String text;

  const _SectionTitle(this.text);

  @override
  Widget build(BuildContext context) => Text(text,
      style: const TextStyle(fontSize: 16.5, fontWeight: FontWeight.bold));
}

/// A selectable mood with its description underneath.
class _MoodChip extends StatelessWidget {
  final String title;
  final String subtitle;
  final bool selected;
  final VoidCallback onTap;

  const _MoodChip({
    required this.title,
    required this.subtitle,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
                color: selected ? accent : Colors.grey.shade300,
                width: selected ? 2 : 1),
            color: selected ? accent.withValues(alpha: 0.06) : null,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Icon(selected ? Icons.check_circle : Icons.circle_outlined,
                    size: 18, color: selected ? accent : Colors.grey),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(title,
                      style: const TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w600)),
                ),
              ]),
              if (subtitle.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(subtitle,
                    style: TextStyle(
                        fontSize: 12.5,
                        color: Colors.grey.shade700,
                        height: 1.35)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _FormatCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _FormatCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
              color: selected ? accent : Colors.grey.shade300,
              width: selected ? 2 : 1),
          color: selected ? accent.withValues(alpha: 0.06) : null,
        ),
        child: Column(children: [
          Icon(icon, size: 30, color: selected ? accent : Colors.grey.shade600),
          const SizedBox(height: 8),
          Text(title,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Text(subtitle,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
        ]),
      ),
    );
  }
}

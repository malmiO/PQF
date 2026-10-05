import 'dart:io';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:gal/gal.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:video_player/video_player.dart';

import '../services/pqf_api.dart';
import '../widgets/error_view.dart';

/// Turns a certified set into a short marketing video.
///
/// WORDING. The framework RECOMMENDS music against a declared standard; it never
/// claims a track is "best" or "optimal", because that is a subjective judgement
/// with no ground truth. The owner listens and chooses. Everything here follows
/// that: a recommended mood with its reason, a preview for every track, and a
/// plain path to continue with no music at all.
class VideoScreen extends StatefulWidget {
  final String productName;

  /// The product category the user entered, used to recommend a music mood.
  final String category;

  /// The certified images, as the ORIGINAL bytes that were scored, in order.
  final List<Uint8List> images;

  /// The role of each image, in the same order as [images].
  final List<String> roles;

  const VideoScreen({
    super.key,
    required this.productName,
    required this.category,
    required this.images,
    required this.roles,
  });

  @override
  State<VideoScreen> createState() => _VideoScreenState();
}

class _VideoScreenState extends State<VideoScreen> {
  final PqfApi _api = PqfApi();
  final AudioPlayer _audio = AudioPlayer();

  bool _loadingMusic = true;
  MusicRecommendation? _music;
  String? _selectedTrackId;
  String? _playingTrackId;

  String _format = 'square'; // 'square' or 'vertical'

  bool _creating = false;
  ApiFailure? _error;

  // The finished video.
  String? _videoPath;
  VideoPlayerController? _videoController;

  @override
  void initState() {
    super.initState();
    _loadMusic();
    _audio.onPlayerComplete.listen((_) {
      if (mounted) setState(() => _playingTrackId = null);
    });
  }

  Future<void> _loadMusic() async {
    final r = await _api.music(widget.category);
    if (!mounted) return;
    setState(() {
      _loadingMusic = false;
      _music = r.ok ? r.value : null;
    });
  }

  Future<void> _togglePreview(MusicTrack t) async {
    try {
      if (_playingTrackId == t.id) {
        await _audio.stop();
        if (mounted) setState(() => _playingTrackId = null);
        return;
      }
      await _audio.stop();
      await _audio.play(UrlSource(_api.musicPreviewUrl(t.id)));
      if (mounted) setState(() => _playingTrackId = t.id);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not play that track.')),
        );
      }
    }
  }

  Future<void> _create() async {
    await _audio.stop();
    setState(() {
      _creating = true;
      _error = null;
      _playingTrackId = null;
    });

    final result = await _api.createVideo(
      images: widget.images,
      roles: widget.roles,
      format: _format,
      trackId: _selectedTrackId,
    );

    if (!mounted) return;
    if (!result.ok) {
      setState(() {
        _creating = false;
        _error = result.failure;
      });
      return;
    }

    // Write the mp4 to a temp file and open it in the player.
    try {
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/pqf_marketing_video.mp4';
      await File(path).writeAsBytes(result.value!, flush: true);
      final controller = VideoPlayerController.file(File(path));
      await controller.initialize();
      await controller.setLooping(true);
      await controller.play();
      if (!mounted) return;
      setState(() {
        _creating = false;
        _videoPath = path;
        _videoController = controller;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _error = ApiFailure.unknown('Could not open the finished video. $e');
      });
    }
  }

  Future<void> _saveVideo() async {
    if (_videoPath == null) return;
    try {
      final has = await Gal.hasAccess(toAlbum: true);
      if (!has && !await Gal.requestAccess(toAlbum: true)) {
        _shareVideo();
        return;
      }
      await Gal.putVideo(_videoPath!, album: 'PQF');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Video saved to your photos.')),
        );
      }
    } catch (e) {
      _shareVideo();
    }
  }

  Future<void> _shareVideo() async {
    if (_videoPath == null) return;
    try {
      await Share.shareXFiles([XFile(_videoPath!)], subject: 'Product video');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not share the video.')),
        );
      }
    }
  }

  @override
  void dispose() {
    _audio.dispose();
    _videoController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Make a video')),
      body: _videoController != null ? _buildResult() : _buildSetup(),
    );
  }

  // ----- Setup: music + format + create -----
  Widget _buildSetup() {
    return ListView(
      padding: const EdgeInsets.all(18),
      children: [
        const Text('Music',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        if (_loadingMusic)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 20),
            child: Center(child: CircularProgressIndicator()),
          )
        else
          _buildMusic(),
        const SizedBox(height: 24),
        const Text('Video shape',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.bold)),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(
            child: _FormatCard(
              title: 'Square',
              subtitle: 'For feeds (1:1)',
              icon: Icons.crop_square,
              selected: _format == 'square',
              onTap: () => setState(() => _format = 'square'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: _FormatCard(
              title: 'Vertical',
              subtitle: 'For Stories and Reels (9:16)',
              icon: Icons.crop_portrait,
              selected: _format == 'vertical',
              onTap: () => setState(() => _format = 'vertical'),
            ),
          ),
        ]),
        const SizedBox(height: 24),
        if (_error != null) ...[
          ErrorView(failure: _error!, onRetry: _create),
          const SizedBox(height: 14),
        ],
        if (_creating)
          Column(children: const [
            CircularProgressIndicator(),
            SizedBox(height: 12),
            Text('Making your video, about 10 seconds',
                style: TextStyle(fontSize: 14.5)),
          ])
        else
          FilledButton.icon(
            style:
                FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
            onPressed: _create,
            icon: const Icon(Icons.movie_creation_outlined),
            label: const Text('Create video'),
          ),
      ],
    );
  }

  Widget _buildMusic() {
    final music = _music;
    if (music == null || music.tracks.isEmpty) {
      return Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: const Color(0xFFF2F2F4),
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Text(
          'No music is installed yet. The video will be made without music.',
          style: TextStyle(fontSize: 14, height: 1.4),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (music.recommendedMood.isNotEmpty) ...[
          Text('Recommended mood: ${music.recommendedMood}',
              style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
          if (music.reason.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(music.reason,
                style: TextStyle(
                    fontSize: 13, color: Colors.grey.shade700, height: 1.35)),
          ],
          const SizedBox(height: 4),
          Text(
            'This is a recommendation. You choose the track, or use none.',
            style: TextStyle(
                fontSize: 12, color: Colors.grey.shade600, height: 1.3),
          ),
          const SizedBox(height: 12),
        ],
        // "No music" is always an explicit, equal choice.
        _TrackTile(
          title: 'No music',
          subtitle: 'Make the video silent.',
          selected: _selectedTrackId == null,
          playing: false,
          onSelect: () => setState(() => _selectedTrackId = null),
          onPreview: null,
        ),
        ...music.tracks.map((t) => _TrackTile(
              title: t.title + (t.recommended ? '  (recommended)' : ''),
              subtitle: t.attribution.isEmpty ? t.mood : t.attribution,
              selected: _selectedTrackId == t.id,
              playing: _playingTrackId == t.id,
              onSelect: () => setState(() => _selectedTrackId = t.id),
              onPreview: () => _togglePreview(t),
            )),
      ],
    );
  }

  // ----- Result: play, save, share -----
  Widget _buildResult() {
    final c = _videoController!;
    return ListView(
      padding: const EdgeInsets.all(18),
      children: [
        const Text('Your video is ready',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 14),
        AspectRatio(
          aspectRatio: c.value.aspectRatio == 0 ? 1 : c.value.aspectRatio,
          child: VideoPlayer(c),
        ),
        const SizedBox(height: 10),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          IconButton(
            iconSize: 34,
            icon: Icon(c.value.isPlaying
                ? Icons.pause_circle
                : Icons.play_circle),
            onPressed: () => setState(() =>
                c.value.isPlaying ? c.pause() : c.play()),
          ),
        ]),
        const SizedBox(height: 10),
        FilledButton.icon(
          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(50)),
          onPressed: _saveVideo,
          icon: const Icon(Icons.save_alt),
          label: const Text('Save to gallery'),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(50)),
          onPressed: _shareVideo,
          icon: const Icon(Icons.ios_share),
          label: const Text('Share'),
        ),
      ],
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

class _TrackTile extends StatelessWidget {
  final String title;
  final String subtitle;
  final bool selected;
  final bool playing;
  final VoidCallback onSelect;
  final VoidCallback? onPreview;

  const _TrackTile({
    required this.title,
    required this.subtitle,
    required this.selected,
    required this.playing,
    required this.onSelect,
    required this.onPreview,
  });

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: BorderSide(
            color: selected ? accent : Colors.transparent,
            width: selected ? 1.6 : 0),
      ),
      child: ListTile(
        leading: Icon(
          selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
          color: selected ? accent : Colors.grey,
        ),
        title: Text(title, style: const TextStyle(fontSize: 14.5)),
        subtitle: subtitle.isEmpty
            ? null
            : Text(subtitle, style: const TextStyle(fontSize: 12)),
        trailing: onPreview == null
            ? null
            : IconButton(
                icon: Icon(playing ? Icons.stop_circle : Icons.play_circle),
                onPressed: onPreview,
              ),
        onTap: onSelect,
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../screens/onboarding_screen.dart';

/// The screen a help sheet is for. Every screen has a "?" that opens its own
/// short help, in the same plain language as the shot briefings.
enum HelpTopic {
  home,
  productForm,
  mode,
  upload,
  capture,
  results,
  makingVideo,
  video,
}

/// Opens the help for [topic].
Future<void> showHelpSheet(BuildContext context,
    [HelpTopic topic = HelpTopic.capture]) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _HelpSheet(topic: topic),
  );
}

/// A "?" button for an app bar.
class HelpButton extends StatelessWidget {
  final HelpTopic topic;
  final Color? color;

  const HelpButton(this.topic, {super.key, this.color});

  @override
  Widget build(BuildContext context) => IconButton(
        icon: Icon(Icons.help_outline, color: color),
        tooltip: 'Help',
        onPressed: () => showHelpSheet(context, topic),
      );
}

/// A good example of one shot type: the owner's own certified photo when it has
/// been added (assets/reference), otherwise the bundled placeholder.
class ReferenceShot {
  final String shotType; // main | angle | detail
  final String title;
  final String line1;
  final String line2;

  const ReferenceShot(this.shotType, this.title, this.line1, this.line2);

  static const all = <ReferenceShot>[
    ReferenceShot('main', 'Main', 'The product in the centre, facing you.',
        'It fills most of the box, on a plain light background.'),
    ReferenceShot('angle', 'Angle', 'The product turned about halfway to one side.',
        'It shows a side the front view hides.'),
    ReferenceShot('detail', 'Detail', 'Close to the most important detail.',
        'A label, a clasp or the texture fills the frame.'),
  ];

  static ReferenceShot? of(String shotType) {
    for (final r in all) {
      if (r.shotType == shotType) return r;
    }
    return null;
  }
}

/// The reference image for a shot type, falling back to the placeholder.
class ReferenceImage extends StatelessWidget {
  final String shotType;
  final double width;
  final double height;

  const ReferenceImage(this.shotType,
      {super.key, this.width = 104, this.height = 130});

  @override
  Widget build(BuildContext context) {
    Widget blank() => Container(
        width: width,
        height: height,
        color: Colors.black12,
        child: const Icon(Icons.image_outlined, color: Colors.black38));
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: Image.asset(
        'assets/reference/$shotType.jpg',
        width: width,
        height: height,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => Image.asset(
          'assets/examples/$shotType.jpg',
          width: width,
          height: height,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => blank(),
        ),
      ),
    );
  }
}

class _Item {
  final IconData icon;
  final String title;
  final String text;
  const _Item(this.icon, this.title, this.text);
}

class _HelpSheet extends StatelessWidget {
  final HelpTopic topic;

  const _HelpSheet({required this.topic});

  static const _lights = <_Item>[
    _Item(Icons.center_focus_strong, 'Focus',
        'How sharp the product looks. Amber: hold the phone steady and tap the '
            'product on screen to focus.'),
    _Item(Icons.wb_sunny_outlined, 'Light',
        'How bright the product is. Amber: raise the brightness with the '
            'slider, or move to better light. White streaks on a shiny product '
            'are glare: put a thin white cloth or paper between the lamp and '
            'the product.'),
    _Item(Icons.wallpaper_outlined, 'Background',
        'How clean and plain the background is. Amber: use a plain white or '
            'light surface. On a grey light box, raise the brightness.'),
    _Item(Icons.crop_free, 'Framing',
        'Whether the product fills the frame well. Amber: move closer or '
            'further so the product sits inside the box. A little zoom helps; '
            'if the zoom number turns amber the photo will be soft, so move '
            'the phone closer instead.'),
  ];

  (String, String, List<_Item>) get _content {
    switch (topic) {
      case HelpTopic.home:
        return ('Start here', 'Each product starts with "New product".', const [
          _Item(Icons.add_circle_outline, 'New product',
              'Tell us about the product, take or choose photos, and get a set '
                  'of photos and a video.'),
          _Item(Icons.wifi, 'Connected',
              'The app needs the photo checking service. If it cannot reach it, '
                  'check the Wi-Fi and try again.'),
        ]);
      case HelpTopic.productForm:
        return ('Product details', 'You only fill this in once per product.', const [
          _Item(Icons.sell_outlined, 'Name and price',
              'The name opens the video. The price is shown at the end.'),
          _Item(Icons.push_pin_outlined, 'Key features',
              'Up to three short things a buyer should notice. They are pointed '
                  'out on your photo in the video.'),
          _Item(Icons.music_note_outlined, 'Video style',
              'Sets the music and the pace. Tap play to listen.'),
          _Item(Icons.crop_portrait, 'Video shape',
              'Vertical for Reels, TikTok and Shorts. Square for the feed.'),
        ]);
      case HelpTopic.mode:
        return ('Two ways to start', 'Both are checked the same way.', const [
          _Item(Icons.camera_alt, 'Take photos with guidance',
              'The camera tells you what to fix and takes each shot for you.'),
          _Item(Icons.photo_library_outlined, 'Use photos I already have',
              'Choose photos from your phone. We tell you which ones to use.'),
        ]);
      case HelpTopic.upload:
        return ('Choosing photos', 'Four to eight photos work best.', const [
          _Item(Icons.view_carousel_outlined, 'Different views',
              'A front view, two different sides, and one close-up.'),
          _Item(Icons.filter_none, 'Same view twice',
              'Two photos of the same view are fine, but only one is used.'),
        ]);
      case HelpTopic.capture:
        return ('What the lights mean',
            'Green means that check passed. Amber means something to fix first.',
            _lights);
      case HelpTopic.results:
        return ('Your results', 'We keep the best four: main, two angles, detail.', const [
          _Item(Icons.check_circle, 'Your set',
              'The photos chosen for your listing and video.'),
          _Item(Icons.filter_none, 'Same view',
              'Not used: another photo in your set already shows this view.'),
          _Item(Icons.check_circle_outline, 'Not needed',
              'A good photo, but your set already has the views it needs.'),
          _Item(Icons.error_outline, 'Not good enough',
              'Not used. The message says what to fix.'),
          _Item(Icons.add_a_photo_outlined, 'Take the missing shots',
              'Opens the camera only for the shots your set still needs.'),
        ]);
      case HelpTopic.makingVideo:
        return ('Making your video', 'You do not need to do anything.', const [
          _Item(Icons.hourglass_empty, 'About a minute',
              'First we plan the video, then we make it.'),
          _Item(Icons.refresh, 'If it stops',
              'Try again repeats only the step that did not finish.'),
        ]);
      case HelpTopic.video:
        return ('Your video', 'It is already saved on your phone.', const [
          _Item(Icons.folder_outlined, 'Saved',
              'Your set photos, the video, the caption and the results are in '
                  'the PQF folder.'),
          _Item(Icons.checklist, 'Ready to post',
              'Green: met. Amber: not met yet, with the measured value.'),
          _Item(Icons.copy, 'Post caption',
              'Copy it and paste it when you post the video.'),
        ]);
    }
  }

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    final (title, intro, items) = _content;
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(22, 4, 22, 22),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title,
                style: const TextStyle(fontSize: 19, fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(intro,
                style: TextStyle(color: Colors.grey.shade700, fontSize: 13.5)),
            const SizedBox(height: 18),
            ...items.map((it) => Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(it.icon, size: 22, color: accent),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(it.title,
                                style: const TextStyle(
                                    fontSize: 15.5,
                                    fontWeight: FontWeight.w600)),
                            const SizedBox(height: 2),
                            Text(it.text,
                                style: const TextStyle(
                                    fontSize: 13.5, height: 1.35)),
                          ],
                        ),
                      ),
                    ],
                  ),
                )),
            if (topic == HelpTopic.capture) ...[
              const SizedBox(height: 4),
              const Text('Good shots',
                  style: TextStyle(fontSize: 16.5, fontWeight: FontWeight.bold)),
              const SizedBox(height: 10),
              ...ReferenceShot.all.map((r) => Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        ReferenceImage(r.shotType, width: 72, height: 90),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(r.title,
                                  style: const TextStyle(
                                      fontSize: 15, fontWeight: FontWeight.w600)),
                              const SizedBox(height: 2),
                              Text('${r.line1}\n${r.line2}',
                                  style: const TextStyle(
                                      fontSize: 13, height: 1.35)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  )),
            ],
            const SizedBox(height: 6),
            TextButton.icon(
              onPressed: () {
                Navigator.of(context).pop();
                Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => const OnboardingScreen()));
              },
              icon: const Icon(Icons.slideshow_outlined, size: 18),
              label: const Text('Show the introduction again'),
            ),
          ],
        ),
      ),
    );
  }
}

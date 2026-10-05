import 'package:flutter/material.dart';

/// A short help sheet: what each live indicator means and what to do when it is
/// amber. Opened from the "?" icon on the capture and results screens.
Future<void> showHelpSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => const _HelpSheet(),
  );
}

class _HelpItem {
  final String name;
  final IconData icon;
  final String meaning;
  final String whenAmber;
  const _HelpItem(this.name, this.icon, this.meaning, this.whenAmber);
}

class _HelpSheet extends StatelessWidget {
  const _HelpSheet();

  static const _items = <_HelpItem>[
    _HelpItem('Focus', Icons.center_focus_strong,
        'How sharp the product looks.',
        'Amber: hold the phone steady and tap the product on screen to focus.'),
    _HelpItem('Light', Icons.wb_sunny_outlined,
        'How bright the product is.',
        'Amber: raise the brightness with the slider, or move to better light.'),
    _HelpItem('Background', Icons.wallpaper_outlined,
        'How clean and plain the background is.',
        'Amber: use a plain white or light surface. On a grey lightbox, raise '
            'the brightness.'),
    _HelpItem('Framing', Icons.crop_free,
        'Whether the product fills the frame well.',
        'Amber: move closer or further so the product sits inside the box.'),
  ];

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(22, 4, 22, 22),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('What the lights mean',
                style: TextStyle(fontSize: 19, fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(
              'Green means that check passed. Amber means there is something to '
              'fix before the photo is taken.',
              style: TextStyle(color: Colors.grey.shade700, fontSize: 13.5),
            ),
            const SizedBox(height: 18),
            ..._items.map((it) => Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(it.icon, size: 22, color: accent),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(it.name,
                                style: const TextStyle(
                                    fontSize: 15.5,
                                    fontWeight: FontWeight.w600)),
                            const SizedBox(height: 2),
                            Text(it.meaning,
                                style: const TextStyle(
                                    fontSize: 13.5, height: 1.3)),
                            const SizedBox(height: 3),
                            Text(it.whenAmber,
                                style: TextStyle(
                                    fontSize: 12.5,
                                    color: Colors.grey.shade700,
                                    height: 1.35)),
                          ],
                        ),
                      ),
                    ],
                  ),
                )),
          ],
        ),
      ),
    );
  }
}

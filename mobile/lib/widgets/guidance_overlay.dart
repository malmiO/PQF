import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import '../services/pqf_api.dart';

/// The live guidance overlay.
///
/// DESIGN INTENT. The user is a non expert seller, not a photographer. Three
/// decisions follow from that.
///
/// One, no numbers are shown. A score of 0.37 means nothing to someone who does
/// not know what sharpness normalisation is. Status is shown instead.
///
/// Two, only one instruction appears at a time. Listing every failing criterion
/// at once produces a wall of correction that a beginner cannot act on. The
/// most important failing check is surfaced and the rest wait their turn.
///
/// Three, status is never carried by colour alone. The banner carries an icon
/// and words as well as its colour, so it still works for a colour blind user
/// and in bright outdoor light where colour is hard to judge.
///
/// v1.1.0: the four indicator lights were removed. They repeated what the one
/// instruction already says and competed with it for attention; the banner now
/// carries the status (green tick: ready, amber bulb: one thing to fix).
class GuidanceOverlay extends StatefulWidget {
  final GuidanceResult guidance;
  final bool waitingForServer;

  /// How long the chip stays open before it collapses to its icon.
  static const Duration collapseAfter = Duration(seconds: 3);

  const GuidanceOverlay({
    super.key,
    required this.guidance,
    this.waitingForServer = false,
  });

  @override
  State<GuidanceOverlay> createState() => _GuidanceOverlayState();
}

/// v1.5.0: ONE instruction chip at the top of the camera. It collapses to its icon
/// after 3 s and opens again when the message changes or when it is tapped.
class _GuidanceOverlayState extends State<GuidanceOverlay> {
  bool _collapsed = false;
  Timer? _timer;
  String _shown = '';

  String get _message {
    final g = widget.guidance;
    if (g.checks.isEmpty)
      return widget.waitingForServer
          ? 'Checking the shot'
          : 'Point the camera at your product';
    return g.ready
        ? 'Looks good. Take the photo'
        : (g.primaryInstruction ?? 'Adjust the shot');
  }

  void _arm() {
    _timer?.cancel();
    _timer = Timer(GuidanceOverlay.collapseAfter, () {
      if (mounted) setState(() => _collapsed = true);
    });
  }

  @override
  void initState() {
    super.initState();
    _shown = _message;
    _arm();
  }

  @override
  void didUpdateWidget(covariant GuidanceOverlay old) {
    super.didUpdateWidget(old);
    if (_message != _shown) {
      _shown = _message;
      _collapsed = false;
      _arm();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final g = widget.guidance;
    return Semantics(
      liveRegion: true,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          setState(() => _collapsed = !_collapsed);
          if (!_collapsed) _arm();
        },
        child: Align(
          alignment: Alignment.center,
          child: _InstructionBanner(
            instruction: g.primaryInstruction,
            ready: g.ready,
            waiting: widget.waitingForServer,
            hasData: g.checks.isNotEmpty,
            collapsed: _collapsed,
          ),
        ),
      ),
    );
  }
}

/// Compact status icons with words (never colour alone): framing, focus, light and
/// background, each with a tick when it passes and a warning mark when it does not.
class GuidanceStatusRow extends StatelessWidget {
  final GuidanceResult guidance;
  const GuidanceStatusRow({super.key, required this.guidance});

  static const _items = <(String, String, IconData)>[
    ('framing', 'Framing', Icons.crop_free),
    ('sharpness', 'Focus', Icons.center_focus_strong_outlined),
    ('exposure', 'Light', Icons.wb_sunny_outlined),
    ('background', 'Background', Icons.wallpaper_outlined),
  ];

  @override
  Widget build(BuildContext context) {
    final byName = {for (final c in guidance.checks) c.name: c.passed};
    return FittedBox(
        fit: BoxFit.scaleDown,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            for (final (key, label, icon) in _items)
              if (byName.containsKey(key))
                Semantics(
                  label:
                      '$label: ${byName[key] == false ? 'needs attention' : 'good'}',
                  excludeSemantics: true,
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    padding:
                        const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.black.withValues(alpha: 0.5),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(icon, size: 13, color: Colors.white),
                      const SizedBox(width: 3),
                      Text(label,
                          style: const TextStyle(
                              color: Colors.white, fontSize: 10.5)),
                      const SizedBox(width: 3),
                      Icon(
                          byName[key] == false
                              ? Icons.error_outline
                              : Icons.check_circle,
                          size: 13,
                          color: byName[key] == false
                              ? const Color(0xFFFFC857)
                              : const Color(0xFF7BD88F)),
                    ]),
                  ),
                ),
          ],
        ));
  }
}

class _InstructionBanner extends StatelessWidget {
  final String? instruction;
  final bool ready;
  final bool waiting;
  final bool hasData;
  final bool collapsed;

  const _InstructionBanner({
    required this.instruction,
    required this.ready,
    required this.waiting,
    required this.hasData,
    this.collapsed = false,
  });

  @override
  Widget build(BuildContext context) {
    late final String text;
    late final Color background;
    late final IconData icon;

    if (!hasData) {
      text = waiting ? 'Checking the shot' : 'Point the camera at your product';
      background = Colors.black.withValues(alpha: 0.62);
      icon = Icons.camera_alt_outlined;
    } else if (ready) {
      text = 'Looks good. Take the photo';
      background = const Color(0xFF2E7D32).withValues(alpha: 0.92);
      icon = Icons.check_circle_outline;
    } else {
      text = instruction ?? 'Adjust the shot';
      background = const Color(0xFFB8860B).withValues(alpha: 0.92);
      icon = Icons.lightbulb_outline;
    }

    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      margin: const EdgeInsets.symmetric(horizontal: 20),
      padding: EdgeInsets.symmetric(
          horizontal: collapsed ? 13 : 16, vertical: collapsed ? 10 : 9),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(26),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: Colors.white, size: 21),
          if (!collapsed) const SizedBox(width: 10),
          if (!collapsed)
            Flexible(
              child: Text(
                text,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14.5,
                  fontWeight: FontWeight.w600,
                  height: 1.2,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// The overall status, shown as the colour of the frame's border. Never the
/// only carrier of status: the instruction banner says it in words.
enum _FramingStatus { checking, good, adjust }

extension _FramingStatusInfo on _FramingStatus {
  Color get color {
    switch (this) {
      case _FramingStatus.good:
        return const Color(0xFF2E7D32); // green
      case _FramingStatus.adjust:
        return const Color(0xFFF2A50C); // amber
      case _FramingStatus.checking:
        return Colors.white;
    }
  }
}

/// The per shot guide drawn inside the scored 4:5 frame (v1.1.0).
enum GuideKind {
  /// Main shot: a centred box, the product inside it.
  box,

  /// Angle: the same box, with a turn arrow beside it.
  boxWithTurn,

  /// Detail: corner brackets near the frame edge: fill the frame.
  corners,
}

/// Where the guide sits for a shot type, in the frame's own coordinates.
/// Guidance only: it shows the target the framing check already uses; it is
/// not a criterion.
class GuideShape {
  /// Main and angle: the box is this share of the frame's height and width.
  static const double boxShare = 0.60;

  /// Detail: brackets this share of the frame's shorter side in from the edge.
  static const double detailInset = 0.04;

  final GuideKind kind;
  final Rect rect;

  const GuideShape(this.kind, this.rect);

  static GuideShape forShot(String shotType, Rect frame) {
    if (shotType == 'detail') {
      return GuideShape(
          GuideKind.corners, frame.deflate(frame.shortestSide * detailInset));
    }
    final box = Rect.fromCenter(
        center: frame.center,
        width: frame.width * boxShare,
        height: frame.height * boxShare);
    return GuideShape(
        shotType == 'angle' ? GuideKind.boxWithTurn : GuideKind.box, box);
  }
}

/// Full frame guide drawn over the preview.
///
/// WHY A FULL FRAME, NOT FOUR CORNERS. Every captured photo is centre cropped to
/// 4:5 (full width kept) before it is scored, so the strips above and below that
/// region are thrown away. The old corner marks showed neither what would be
/// kept nor what would be discarded, so a user framed against the whole 9:16
/// preview and the room above and below the product was scored as dirty
/// background. This overlay darkens everything outside the scored 4:5 region and
/// draws a status coloured border around it, so the user sees exactly what will
/// be scored, with a per shot target inside it.
class ScoredRegionGuide extends StatelessWidget {
  final GuidanceResult guidance;
  final bool waiting;

  /// main | angle | detail | extra, from the current ShotPlan step.
  final String shotType;

  /// The UNGUIDED study condition (v1.1.0): the same scored 4:5 region is shown
  /// (same crop), but no status, no caption and no framing target.
  final bool neutral;

  /// The detected product box, normalised [x, y, w, h] within the scored 4:5
  /// region, or null. Drawn as a thin outline next to the target box (guided
  /// only, display only — 2026-10-13).
  final List<double>? productBox;

  const ScoredRegionGuide({
    super.key,
    required this.guidance,
    required this.waiting,
    required this.shotType,
    this.neutral = false,
    this.productBox,
  });

  @override
  Widget build(BuildContext context) {
    if (neutral) {
      return IgnorePointer(
        child: LayoutBuilder(builder: (context, c) {
          final rectH = math.min(c.maxWidth * 5 / 4, c.maxHeight);
          final rect =
              Rect.fromLTWH(0, (c.maxHeight - rectH) / 2, c.maxWidth, rectH);
          return CustomPaint(
            size: Size(c.maxWidth, c.maxHeight),
            painter:
                _ScoredRegionPainter(rect: rect, borderColor: Colors.white70),
          );
        }),
      );
    }
    final hasData = guidance.checks.isNotEmpty;
    final status = !hasData
        ? _FramingStatus.checking
        : (guidance.ready ? _FramingStatus.good : _FramingStatus.adjust);
    // The guide turns green when the existing /guidance framing check passes
    // (v1.1.0); one instruction is shown below the frame, not here.
    final framingOk = guidance.framingOk == true;

    return IgnorePointer(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final w = constraints.maxWidth;
          final h = constraints.maxHeight;

          // The scored region in PREVIEW coordinates: full preview width, height
          // = width x 5 / 4 (aspect 4:5), centred vertically. This matches the
          // server's centre crop of the captured photo. CameraPreview fills the
          // Stack (StackFit.expand), so the full preview width is the full image
          // width the server keeps. Clamp the height so it never exceeds the
          // preview; a very tall preview then leaves darkened strips above and
          // below, which is where all text sits.
          final rectH = math.min(w * 5 / 4, h);
          final rect = Rect.fromLTWH(0, (h - rectH) / 2, w, rectH);
          // Map the normalised product box into the scored rectangle.
          Rect? boxRect;
          final pb = productBox;
          if (pb != null && pb.length == 4) {
            boxRect = Rect.fromLTWH(
              rect.left + pb[0] * rect.width,
              rect.top + pb[1] * rect.height,
              pb[2] * rect.width,
              pb[3] * rect.height,
            );
          }
          return CustomPaint(
            size: Size(w, h),
            painter: _ScoredRegionPainter(
              rect: rect,
              borderColor: status.color,
              guide: GuideShape.forShot(shotType, rect),
              guideOk: framingOk,
              productBox: boxRect,
            ),
          );
        },
      ),
    );
  }
}

class _ScoredRegionPainter extends CustomPainter {
  final Rect rect;
  final Color borderColor;

  /// The per shot guide; null draws the frame only (UNGUIDED study condition).
  final GuideShape? guide;

  /// The framing check passed: the guide is drawn solid green.
  final bool guideOk;

  /// The detected product box in preview coordinates, or null. Drawn as a thin
  /// outline so the user sees what the framing check found (display only).
  final Rect? productBox;

  _ScoredRegionPainter({
    required this.rect,
    required this.borderColor,
    this.guide,
    this.guideOk = false,
    this.productBox,
  });

  static const _green = Color(0xFF2E7D32);

  @override
  void paint(Canvas canvas, Size size) {
    final dim = Paint()..color = Colors.black.withValues(alpha: 0.55);

    // Darken everything OUTSIDE the scored rectangle. With a full width
    // rectangle only the top and bottom strips exist, but the left/right rects
    // are drawn too so this stays correct if the preview is ever not full width.
    if (rect.top > 0) {
      canvas.drawRect(Rect.fromLTRB(0, 0, size.width, rect.top), dim);
    }
    if (rect.bottom < size.height) {
      canvas.drawRect(
          Rect.fromLTRB(0, rect.bottom, size.width, size.height), dim);
    }
    if (rect.left > 0) {
      canvas.drawRect(Rect.fromLTRB(0, rect.top, rect.left, rect.bottom), dim);
    }
    if (rect.right < size.width) {
      canvas.drawRect(
          Rect.fromLTRB(rect.right, rect.top, size.width, rect.bottom), dim);
    }

    // Solid rounded border around the scored region, coloured by status.
    final border = Paint()
      ..color = borderColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;
    final rrect = RRect.fromRectAndRadius(rect, const Radius.circular(16));
    canvas.drawRRect(rrect, border);

    // The detected product box: a thin cyan outline with a dark under-stroke,
    // drawn next to the target box so the user sees what was detected. Display
    // only; never carries pass/fail (that is the border and banner).
    final pb = productBox;
    if (pb != null && pb.width > 0 && pb.height > 0) {
      final boxUnder = Paint()
        ..color = Colors.black.withValues(alpha: 0.35)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3;
      final boxPaint = Paint()
        ..color = const Color(0xFF29B6F6).withValues(alpha: 0.95)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5;
      final rr = RRect.fromRectAndRadius(pb, const Radius.circular(6));
      canvas.drawRRect(rr, boxUnder);
      canvas.drawRRect(rr, boxPaint);
    }

    final g = guide;
    if (g == null) return;
    // The guide: dashed white while adjusting, solid green once the framing
    // check passes. A dark under-stroke keeps it visible on a white background.
    final under = Paint()
      ..color = Colors.black.withValues(alpha: 0.35)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4.5;
    final paint = Paint()
      ..color = guideOk ? _green : Colors.white.withValues(alpha: 0.95)
      ..style = PaintingStyle.stroke
      ..strokeWidth = guideOk ? 3.5 : 2.5
      ..strokeCap = StrokeCap.round;
    switch (g.kind) {
      case GuideKind.box:
      case GuideKind.boxWithTurn:
        final box = RRect.fromRectAndRadius(g.rect, const Radius.circular(12));
        if (guideOk) {
          canvas.drawRRect(box, under);
          canvas.drawRRect(box, paint);
        } else {
          _drawDashedRRect(canvas, box, under);
          _drawDashedRRect(canvas, box, paint);
        }
        if (g.kind == GuideKind.boxWithTurn)
          _drawTurnArrow(canvas, g.rect, under, paint);
      case GuideKind.corners:
        final len = g.rect.shortestSide * 0.14;
        final path = Path();
        final r = g.rect;
        for (final (corner, dx, dy) in [
          (r.topLeft, 1.0, 1.0),
          (r.topRight, -1.0, 1.0),
          (r.bottomLeft, 1.0, -1.0),
          (r.bottomRight, -1.0, -1.0),
        ]) {
          path
            ..moveTo(corner.dx + dx * len, corner.dy)
            ..lineTo(corner.dx, corner.dy)
            ..lineTo(corner.dx, corner.dy + dy * len);
        }
        final thick = Paint()
          ..color = paint.color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 4
          ..strokeCap = StrokeCap.round;
        canvas.drawPath(path, under..strokeWidth = 6);
        canvas.drawPath(path, thick);
    }
  }

  /// A curved arrow to the right of the box: "turn the product".
  void _drawTurnArrow(Canvas canvas, Rect box, Paint under, Paint paint) {
    // Fits the space between the box and the frame edge, with a margin for the
    // arrow head and the stroke.
    final space = rect.right - box.right;
    final radius = math.min(box.height * 0.12, space * 0.30);
    final centre = Offset(box.right + space / 2, box.center.dy);
    final arc = Rect.fromCircle(center: centre, radius: radius);
    const start = -math.pi * 0.75, sweep = math.pi * 1.25;
    final path = Path()..addArc(arc, start, sweep);
    final end = Offset(centre.dx + radius * math.cos(start + sweep),
        centre.dy + radius * math.sin(start + sweep));
    final tangent = start + sweep + math.pi / 2; // direction of travel
    final head = radius * 0.45;
    for (final side in [-0.5, 0.5]) {
      final a = tangent + math.pi + side;
      path
        ..moveTo(end.dx, end.dy)
        ..lineTo(end.dx + head * math.cos(a), end.dy + head * math.sin(a));
    }
    final solid = Paint()
      ..color = paint.color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(path, under);
    canvas.drawPath(path, solid);
  }

  void _drawDashedRRect(Canvas canvas, RRect rrect, Paint paint,
      {double dash = 9, double gap = 6}) {
    final path = Path()..addRRect(rrect);
    for (final metric in path.computeMetrics()) {
      var dist = 0.0;
      while (dist < metric.length) {
        final len = math.min(dash, metric.length - dist);
        canvas.drawPath(metric.extractPath(dist, dist + len), paint);
        dist += dash + gap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _ScoredRegionPainter old) =>
      old.rect != rect ||
      old.borderColor != borderColor ||
      old.guide?.kind != guide?.kind ||
      old.guide?.rect != guide?.rect ||
      old.guideOk != guideOk ||
      old.productBox != productBox;
}

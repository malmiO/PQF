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
/// Three, status is never carried by colour alone. Each indicator also carries
/// an icon and a label, so the interface still works for a colour blind user
/// and in bright outdoor light where colour is hard to judge.
class GuidanceOverlay extends StatelessWidget {
  final GuidanceResult guidance;
  final bool waitingForServer;

  const GuidanceOverlay({
    super.key,
    required this.guidance,
    this.waitingForServer = false,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        _IndicatorRow(checks: guidance.checks, waiting: waitingForServer),
        const SizedBox(height: 14),
        _InstructionBanner(
          instruction: guidance.primaryInstruction,
          ready: guidance.ready,
          waiting: waitingForServer,
          hasData: guidance.checks.isNotEmpty,
        ),
      ],
    );
  }
}

class _IndicatorRow extends StatelessWidget {
  final List<CriterionResult> checks;
  final bool waiting;

  const _IndicatorRow({required this.checks, required this.waiting});

  @override
  Widget build(BuildContext context) {
    if (checks.isEmpty) {
      return const SizedBox(height: 62);
    }
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: checks
          .map((c) => Padding(
                padding: const EdgeInsets.symmetric(horizontal: 7),
                child: _Indicator(check: c, dimmed: waiting),
              ))
          .toList(),
    );
  }
}

class _Indicator extends StatelessWidget {
  final CriterionResult check;
  final bool dimmed;

  const _Indicator({required this.check, required this.dimmed});

  @override
  Widget build(BuildContext context) {
    final ok = check.passed ?? false;
    final color = ok ? const Color(0xFF2E7D32) : const Color(0xFFC62828);
    final icon = ok ? Icons.check_circle : Icons.error;

    return AnimatedOpacity(
      opacity: dimmed ? 0.55 : 1.0,
      duration: const Duration(milliseconds: 180),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
              boxShadow: const [
                BoxShadow(color: Colors.black38, blurRadius: 6, offset: Offset(0, 2)),
              ],
            ),
            child: Icon(icon, color: Colors.white, size: 19),
          ),
          const SizedBox(height: 6),
          Text(
            check.label,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
              shadows: [Shadow(color: Colors.black87, blurRadius: 4)],
            ),
          ),
        ],
      ),
    );
  }
}

class _InstructionBanner extends StatelessWidget {
  final String? instruction;
  final bool ready;
  final bool waiting;
  final bool hasData;

  const _InstructionBanner({
    required this.instruction,
    required this.ready,
    required this.waiting,
    required this.hasData,
  });

  @override
  Widget build(BuildContext context) {
    late final String text;
    late final Color background;
    late final IconData icon;

    if (!hasData) {
      text = waiting ? 'Checking the shot' : 'Point the camera at your product';
      background = Colors.black.withOpacity(0.62);
      icon = Icons.camera_alt_outlined;
    } else if (ready) {
      text = 'Looks good. Take the photo';
      background = const Color(0xFF2E7D32).withOpacity(0.92);
      icon = Icons.check_circle_outline;
    } else {
      text = instruction ?? 'Adjust the shot';
      background = const Color(0xFFB8860B).withOpacity(0.92);
      icon = Icons.lightbulb_outline;
    }

    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      margin: const EdgeInsets.symmetric(horizontal: 20),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(26),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: Colors.white, size: 21),
          const SizedBox(width: 10),
          Flexible(
            child: Text(
              text,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 15.5,
                fontWeight: FontWeight.w600,
                height: 1.25,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The framing status, carried by colour AND an icon and a word (never colour
/// alone), so it still reads for a colour blind user and in bright light.
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

  IconData get icon {
    switch (this) {
      case _FramingStatus.good:
        return Icons.check_circle;
      case _FramingStatus.adjust:
        return Icons.error_outline;
      case _FramingStatus.checking:
        return Icons.hourglass_top;
    }
  }

  String get word {
    switch (this) {
      case _FramingStatus.good:
        return 'Good';
      case _FramingStatus.adjust:
        return 'Adjust';
      case _FramingStatus.checking:
        return 'Checking';
    }
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

  const ScoredRegionGuide({
    super.key,
    required this.guidance,
    required this.waiting,
    required this.shotType,
    this.neutral = false,
  });

  @override
  Widget build(BuildContext context) {
    if (neutral) {
      return IgnorePointer(
        child: LayoutBuilder(builder: (context, c) {
          final rectH = math.min(c.maxWidth * 5 / 4, c.maxHeight);
          final rect = Rect.fromLTWH(0, (c.maxHeight - rectH) / 2, c.maxWidth, rectH);
          return CustomPaint(
            size: Size(c.maxWidth, c.maxHeight),
            painter: _ScoredRegionPainter(
                rect: rect, borderColor: Colors.white70, showInnerBox: false),
          );
        }),
      );
    }
    final hasData = guidance.checks.isNotEmpty;
    final status = !hasData
        ? _FramingStatus.checking
        : (guidance.ready ? _FramingStatus.good : _FramingStatus.adjust);

    final showInnerBox = shotType != 'detail';
    final String caption;
    if (shotType == 'detail') {
      caption = 'Fill the frame with the label or texture';
    } else if (shotType == 'angle') {
      caption = 'Turn the product about 30 to 45 degrees';
    } else {
      caption = 'Place the product inside the box';
    }

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
          final top = (h - rectH) / 2;
          final rect = Rect.fromLTWH(0, top, w, rectH);

          return Stack(
            children: [
              Positioned.fill(
                child: CustomPaint(
                  painter: _ScoredRegionPainter(
                    rect: rect,
                    borderColor: status.color,
                    showInnerBox: showInnerBox,
                  ),
                ),
              ),
              // Status chip, in the darkened strip ABOVE the scored region so it
              // never covers the product.
              Positioned(
                top: (top - 44).clamp(8.0, double.infinity),
                left: 0,
                right: 0,
                child: Center(child: _StatusChip(status: status)),
              ),
              // Per shot caption, in the darkened strip BELOW the scored region.
              Positioned(
                top: top + rectH + 10,
                left: 24,
                right: 24,
                child: Text(
                  caption,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.95),
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    shadows: const [Shadow(color: Colors.black87, blurRadius: 5)],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

/// A small pill showing the framing status as icon + word, so status is never
/// carried by the border colour alone.
class _StatusChip extends StatelessWidget {
  final _FramingStatus status;

  const _StatusChip({required this.status});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: status.color, width: 1.5),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(status.icon, color: status.color, size: 17),
          const SizedBox(width: 6),
          Text(
            status.word,
            style: TextStyle(
              color: status.color,
              fontSize: 13,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _ScoredRegionPainter extends CustomPainter {
  final Rect rect;
  final Color borderColor;
  final bool showInnerBox;

  _ScoredRegionPainter({
    required this.rect,
    required this.borderColor,
    required this.showInnerBox,
  });

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

    // Per shot target: a centred dashed box covering about 50% of the scored
    // region's area (side factor sqrt(0.5)). Omitted for a detail close up,
    // which is meant to fill the whole frame.
    if (showInnerBox) {
      const factor = 0.7071; // sqrt(0.5): 50% of the area
      final boxW = rect.width * factor;
      final boxH = rect.height * factor;
      final box = Rect.fromCenter(
          center: rect.center, width: boxW, height: boxH);
      final dashPaint = Paint()
        ..color = Colors.white.withValues(alpha: 0.9)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2;
      _drawDashedRRect(
          canvas, RRect.fromRectAndRadius(box, const Radius.circular(10)),
          dashPaint);
    }
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
      old.showInnerBox != showInnerBox;
}

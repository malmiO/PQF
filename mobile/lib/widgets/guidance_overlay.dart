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
                padding: const EdgeInsets.symmetric(horizontal: 10),
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
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
              boxShadow: const [
                BoxShadow(color: Colors.black38, blurRadius: 6, offset: Offset(0, 2)),
              ],
            ),
            child: Icon(icon, color: Colors.white, size: 22),
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

/// Framing guide drawn over the preview.
///
/// Catalogue composition wants the product centred with clear margin. Drawing
/// the target region removes the guesswork, and it is the cheapest guidance in
/// the whole app because it costs nothing to compute.
class FramingGuide extends StatelessWidget {
  const FramingGuide({super.key});

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      // Positioned in the UPPER portion of the preview rather than centred.
      // The instruction and guidance panels occupy the lower half, and a
      // centred box put them directly over the product, hiding exactly what
      // the user needs to see while framing it.
      child: Align(
        alignment: const Alignment(0, -0.42),
        child: FractionallySizedBox(
          widthFactor: 0.68,
          heightFactor: 0.34,
          child: Stack(
            children: [
              // Corner marks rather than a full rectangle. A closed box reads
              // as a boundary the product must not cross. Corners suggest the
              // area to fill without hiding the edges of the product itself.
              Positioned.fill(
                child: CustomPaint(painter: _CornerPainter()),
              ),
              Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text(
                    'Fill this area with your product',
                    style: TextStyle(
                      color: Colors.white.withOpacity(0.92),
                      fontSize: 11.5,
                      shadows: const [
                        Shadow(color: Colors.black87, blurRadius: 5)
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CornerPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white.withOpacity(0.85)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;

    final len = size.width * 0.14;

    // top left
    canvas.drawLine(const Offset(0, 0), Offset(len, 0), paint);
    canvas.drawLine(const Offset(0, 0), Offset(0, len), paint);
    // top right
    canvas.drawLine(Offset(size.width, 0), Offset(size.width - len, 0), paint);
    canvas.drawLine(Offset(size.width, 0), Offset(size.width, len), paint);
    // bottom left
    canvas.drawLine(Offset(0, size.height), Offset(len, size.height), paint);
    canvas.drawLine(Offset(0, size.height), Offset(0, size.height - len), paint);
    // bottom right
    canvas.drawLine(Offset(size.width, size.height),
        Offset(size.width - len, size.height), paint);
    canvas.drawLine(Offset(size.width, size.height),
        Offset(size.width, size.height - len), paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

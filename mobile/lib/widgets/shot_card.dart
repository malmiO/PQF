import 'package:flutter/material.dart';

import '../models/shot_plan.dart';
import 'help_sheet.dart';

/// The card shown before every shot, in BOTH study conditions (2026-10-15).
///
/// The CORE is the same words in the unguided and the guided condition: the shot name
/// and its one-line description (ShotStep.label and ShotStep.instruction). That is all
/// condition A sees, so both conditions are told what each shot is, including the detail
/// shot, and only the live guidance differs.
///
/// Condition B keeps its extra guided content ON TOP of the core: the "Shot n of N"
/// counter, the reference example, the reason, and the note that the camera will check
/// the shot. None of it appears when [guided] is false, and nothing here makes a
/// /guidance call or shows a measured message, an outline or a help card.
class ShotCard extends StatelessWidget {
  final ShotStep step;
  final bool guided;
  final int shotNumber;
  final int total;
  final bool optional;
  final bool canFinishInstead;
  final VoidCallback onReady;
  final VoidCallback onFinish;

  const ShotCard({
    super.key,
    required this.step,
    required this.guided,
    required this.shotNumber,
    required this.total,
    required this.optional,
    required this.canFinishInstead,
    required this.onReady,
    required this.onFinish,
  });

  /// Key of the part that must read identically in both conditions (tested).
  static const coreKey = ValueKey('shot-card-core');

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFF12161C).withValues(alpha: 0.96),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(26, 20, 26, 26),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (guided) ...[
                Text(
                  optional ? 'Optional extra shot' : 'Shot $shotNumber of $total',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.6),
                    fontSize: 13,
                    letterSpacing: 0.6,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 10),
              ],
              // ---- the core: identical in both conditions ----
              Column(
                key: coreKey,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    step.label,
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 30,
                        fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 26),
                  Text(
                    step.instruction,
                    style: const TextStyle(
                        color: Colors.white, fontSize: 19, height: 1.45),
                  ),
                ],
              ),
              // ---- guided only, on top of the core ----
              if (guided) ...[
                // A good example of this shot: the owner's own certified photo
                // once added to assets/reference (v1.1.0), else the placeholder.
                if (ReferenceShot.of(step.shotType) != null) ...[
                  const SizedBox(height: 18),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ReferenceImage(step.shotType),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Text(
                          'A good ${step.label.toLowerCase()} shot:\n'
                          '${ReferenceShot.of(step.shotType)!.line1}\n'
                          '${ReferenceShot.of(step.shotType)!.line2}',
                          style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.75),
                              fontSize: 13.5,
                              height: 1.4),
                        ),
                      ),
                    ],
                  ),
                ],
                const SizedBox(height: 18),
                Container(
                  padding: const EdgeInsets.all(15),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.07),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.lightbulb_outline,
                          color: Colors.amber.shade300, size: 19),
                      const SizedBox(width: 11),
                      Expanded(
                        child: Text(
                          step.why,
                          style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.85),
                              fontSize: 14.5,
                              height: 1.4),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              const Spacer(),
              if (guided)
                Text(
                  'When you tap ready, the camera will check the shot and tell '
                  'you what to fix.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.55),
                      fontSize: 13,
                      height: 1.4),
                ),
              if (guided) const SizedBox(height: 16),
              FilledButton(
                style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(52)),
                onPressed: onReady,
                child: const Text('I am ready'),
              ),
              if (canFinishInstead) ...[
                const SizedBox(height: 8),
                TextButton(
                  onPressed: onFinish,
                  child: Text('Finish and check my photos',
                      style:
                          TextStyle(color: Colors.white.withValues(alpha: 0.8))),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

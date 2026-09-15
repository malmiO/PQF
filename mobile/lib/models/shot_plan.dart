/// The guided shot sequence.
///
/// WHY THIS EXISTS. The quality gate requires a set with coverage, meaning at
/// least one main shot, at least two angles and at least one detail shot. A
/// user who does not know that takes five near identical front views and the
/// set is rejected after they have finished, which is a poor experience and
/// teaches them nothing.
///
/// Encoding the gate's requirements as a sequence turns that failure into
/// something the app prevents rather than reports, and it teaches the coverage
/// a listing actually needs. The instructions themselves carry the photographic
/// knowledge the framework exists to transfer.
class ShotStep {
  /// Short label shown in the progress strip.
  final String label;

  /// What to do, in one line, written for someone with no photography training.
  final String instruction;

  /// A short reason. Users follow guidance more reliably when they know why.
  final String why;

  /// The role this shot is intended to satisfy in the quality gate. Used only
  /// for reporting. The framework classifies the image on its own evidence and
  /// is never told what role was intended.
  final String intendedRole;

  const ShotStep({
    required this.label,
    required this.instruction,
    required this.why,
    required this.intendedRole,
  });
}

class ShotPlan {
  /// Four required shots plus one optional, which satisfies a gate requiring
  /// one main shot, two angles, one detail, and a set of four to six images.
  static const List<ShotStep> steps = [
    ShotStep(
      label: 'Main',
      instruction: 'Place the product in the centre, facing you, and fill the box.',
      why: 'This becomes the first photo a customer sees.',
      intendedRole: 'hero_shot',
    ),
    ShotStep(
      label: 'Angle 1',
      instruction: 'Turn the product about halfway to one side.',
      why: 'A second view shows shape and depth that a front view hides.',
      intendedRole: 'angle_shot',
    ),
    ShotStep(
      label: 'Angle 2',
      instruction: 'Now show the other side, or the back.',
      why: 'Customers ask what the other side looks like. Answer it in advance.',
      intendedRole: 'angle_shot',
    ),
    ShotStep(
      label: 'Detail',
      instruction: 'Move closer and fill the frame with the most important detail, '
          'such as a label, a clasp, or the texture.',
      why: 'Close detail is what convinces someone the quality is real.',
      intendedRole: 'detail_shot',
    ),
    ShotStep(
      label: 'Extra',
      instruction: 'One more if you want. Any view you think helps.',
      why: 'Optional. You can finish now instead.',
      intendedRole: 'any',
    ),
  ];

  /// Shots below this index must be taken before finishing.
  static const int requiredCount = 4;

  static ShotStep at(int index) =>
      steps[index.clamp(0, steps.length - 1)];

  static bool isOptional(int index) => index >= requiredCount;

  static bool isComplete(int captured) => captured >= requiredCount;

  /// Confirmation shown immediately after a capture, before the next
  /// instruction. Brief, because the user wants to keep moving.
  static String confirmation(int justCaptured) {
    if (justCaptured >= steps.length) return 'That is everything. Well done.';
    if (justCaptured == requiredCount) {
      return 'You have everything you need. Finish now, or take one more.';
    }
    return 'Got it. Next, ${steps[justCaptured].label.toLowerCase()}.';
  }
}

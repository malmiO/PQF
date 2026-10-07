import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/services/pqf_api.dart';
import 'package:mobile/widgets/guidance_overlay.dart';

// Framing guide (v1.1.0, Part B): a guide per shot inside the 4:5 frame, green
// when the existing framing check passes, and one instruction at a time.
void main() {
  const frame = Rect.fromLTWH(0, 100, 400, 500); // a 4:5 scored region

  test('main shot: a centred box 60 percent of the frame', () {
    final g = GuideShape.forShot('main', frame);
    expect(g.kind, GuideKind.box);
    expect(g.rect.center, frame.center);
    expect(g.rect.height, closeTo(frame.height * 0.60, 1e-9));
    expect(g.rect.width, closeTo(frame.width * 0.60, 1e-9));
  });

  test('angle shot: the same box, with the turn arrow', () {
    final g = GuideShape.forShot('angle', frame);
    expect(g.kind, GuideKind.boxWithTurn);
    expect(g.rect, GuideShape.forShot('main', frame).rect);
  });

  test('detail shot: corner brackets that nearly fill the frame', () {
    final g = GuideShape.forShot('detail', frame);
    expect(g.kind, GuideKind.corners);
    expect(g.rect.height / frame.height, greaterThan(0.9));
    expect(frame.contains(g.rect.topLeft) && frame.contains(g.rect.bottomRight - const Offset(1, 1)),
        isTrue);
  });

  CriterionResult c(String name, bool passed) =>
      CriterionResult(name: name, score: passed ? 0.9 : 0.2, weight: 0, passed: passed);

  test('one instruction: framing first, then focus, light, background', () {
    // the server lists one line per failing check, in check order
    final g = GuidanceResult(
      ready: false,
      checks: [c('sharpness', false), c('exposure', false), c('background', true),
               c('framing', false)],
      feedback: ['Hold steady', 'Brighter please', 'Move closer'],
      elapsedMs: 0,
    );
    expect(g.primaryInstruction, 'Move closer');
    expect(g.framingOk, isFalse);

    final noFraming = GuidanceResult(
      ready: false,
      checks: [c('sharpness', true), c('exposure', false), c('background', false),
               c('framing', true)],
      feedback: ['Brighter please', 'Plain background please'],
      elapsedMs: 0,
    );
    expect(noFraming.primaryInstruction, 'Brighter please');
    expect(noFraming.framingOk, isTrue);
  });

  test('no reading yet: no instruction and no framing status', () {
    final g = GuidanceResult.empty();
    expect(g.primaryInstruction, isNull);
    expect(g.framingOk, isNull);
  });
}

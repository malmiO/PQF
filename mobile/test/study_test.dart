import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/study_session.dart';
import 'package:mobile/services/study_log.dart';

void main() {
  tearDown(() => StudySession.current = null);

  StudySession session(String p, int n) =>
      StudySession(participant: p, product: 'K1', session: n);

  test('unguided condition never sends guidance; guided and normal use do', () {
    StudySession.current = null;
    expect(GuidancePolicy.guided(StudySession.current), isTrue);

    // P01 is UNGUIDED first, P02 GUIDED first (ABBA over participants)
    StudySession.current = session('P01', 1);
    expect(StudySession.current!.condition, StudySession.unguided);
    expect(GuidancePolicy.guided(StudySession.current), isFalse);

    StudySession.current = session('P01', 2);
    expect(GuidancePolicy.guided(StudySession.current), isTrue);
  });

  test('ABBA order matches the server (P01 AB, P02 BA, P03 BA, P04 AB)', () {
    const a = [StudySession.unguided, StudySession.guided];
    const b = [StudySession.guided, StudySession.unguided];
    final orders = [
      for (var n = 1; n <= 8; n++)
        StudySession.abbaOrder('P${n.toString().padLeft(2, '0')}')
    ];
    expect(orders, [a, b, b, a, a, b, b, a]);
  });

  test('codes only: names and contacts are not valid codes', () {
    expect(StudySession.participantPattern.hasMatch('P07'), isTrue);
    expect(StudySession.participantPattern.hasMatch('Nimal'), isFalse);
    expect(StudySession.productPattern.hasMatch('K1'), isTrue);
    expect(StudySession.productPattern.hasMatch('call 0771234567'), isFalse);
  });

  test('photos are identified by SHA-256, not sent', () {
    final h = StudyLog.photoHash(Uint8List.fromList([1, 2, 3]));
    expect(h, hasLength(64));
    expect(h, '039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81');
  });
}

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mobile/models/study_session.dart';
import 'package:mobile/services/pqf_api.dart';
import 'package:mobile/services/study_log.dart';

/// The study log payloads the app really builds (v1.4.0, 2026-10-15).
///
/// StudyLog's own code builds every entry and POSTs it to /study/log. Here that POST is
/// captured with a mock HTTP client, so the bodies are exactly what the phone would send.
/// The backend test (backend/tests/test_study_payloads_2026_10_15.py) posts the saved
/// copy, mobile/test/fixtures/study_payloads.jsonl, to the real validator.
///
/// Refresh the fixture with:  PQF_WRITE_FIXTURE=1 flutter test test/study_payloads_test.dart
///
/// help_card_shown, setup_check_shown, restart and capture_end are built inline in
/// capture_screen.dart; their maps are repeated here exactly as the screen writes them.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('the app builds the payloads the server must accept', () async {
    final fx = jsonDecode(File('test/fixtures/batch_breakdown.json').readAsStringSync())
        as Map<String, dynamic>;
    final batch = BatchResult.fromJson(fx['batch'] as Map<String, dynamic>);
    final photos = [
      for (var i = 0; i < batch.images.length; i++)
        Uint8List.fromList(List<int>.generate(64, (k) => (i * 31 + k * 7) % 251))
    ];

    final bodies = <String>[];
    final client = MockClient((req) async {
      if (req.url.path == '/study/log') bodies.add(req.body);
      return http.Response('{"ok":true}', 200);
    });

    // Session 2 of participant P03 (a GUIDED session), same product as the first.
    StudySession.current = StudySession(
      participant: 'P03',
      product: 'K1',
      session: 2,
      group: StudySession.seller,
      sameProductAsFirst: true,
    );
    addTearDown(() => StudySession.current = null);

    await http.runWithClient(() async {
      await StudyLog.sessionStart(StudySession.current!);
      final first = photos.first;
      await StudyLog.photoCaptured(
        bytes: first,
        shotRequested: 'main',
        retakeOf: null,
        source: 'in_app',
        width: 3096,
        height: 4128,
        exifOrientation: 1,
      );
      await StudyLog.photoCaptured(
        bytes: photos[1],
        shotRequested: 'main',
        retakeOf: StudyLog.photoHash(first), // a retake of the first
        source: 'in_app',
        width: null,
        height: null,
        exifOrientation: null,
      );
      await StudyLog.log('help_card_shown', {'role': 'hero_shot', 'seconds': 9});
      await StudyLog.log('setup_check_shown', {'role': 'angle_shot', 'retakes': 3});
      await StudyLog.log('restart', {'role': null, 'photos_kept': 4});
      await StudyLog.log('capture_end',
          {'photo_hashes': photos.map(StudyLog.photoHash).toList()});
      await StudyLog.ownPicks({
        'main': photos[0],
        'angle1': photos[1],
        'angle2': photos[2],
        'detail': photos[3],
      });
      await StudyLog.batchResult(photos, batch);
      await StudyLog.log('video_ready');
    }, () => client);

    expect(bodies.length, 10);
    final events = bodies.map((b) => (jsonDecode(b) as Map)['event']).toList();
    expect(events, [
      'session_start',
      'photo_captured',
      'photo_captured',
      'help_card_shown',
      'setup_check_shown',
      'restart',
      'capture_end',
      'own_picks',
      'batch_result',
      'video_ready',
    ]);

    final start = jsonDecode(bodies.first) as Map<String, dynamic>;
    expect(start['group'], 'seller');
    expect(start['condition_order'], hasLength(2));
    expect(start['same_product_as_first'], true);
    expect(start['apk_version'], '${start['app_version']}+${start['app_build']}');

    if (Platform.environment['PQF_WRITE_FIXTURE'] == '1') {
      File('test/fixtures/study_payloads.jsonl')
          .writeAsStringSync('${bodies.join('\n')}\n');
    }
  });
}

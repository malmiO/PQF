import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/study_session.dart';
import 'package:mobile/services/study_data.dart';
import 'package:mobile/services/study_log.dart';

/// Prompt 05: the study's photos are kept byte-identical to what was hashed, and
/// exported as one zip laid out as research/evaluation/make_blind_packs.py expects.

/// A fake "photo": a JPEG-looking header, seeded noise, a JPEG trailer. Distinct per seed.
Uint8List fakePhoto(int seed, {int size = 4096}) {
  var x = seed * 2654435761 % 4294967296;
  final b = BytesBuilder()..add([0xFF, 0xD8, 0xFF, 0xE0]);
  for (var i = 0; i < size; i++) {
    x = (x * 1103515245 + 12345) % 2147483648;
    b.addByte((x >> 16) & 0xFF);
  }
  b.add([0xFF, 0xD9]);
  return b.toBytes();
}

String sha(List<int> bytes) => sha256.convert(bytes).toString();

void main() {
  late Directory tmp;
  late Directory study;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('pqf_study_test_');
    study = Directory('${tmp.path}/study');
    StudySession.current = null;
  });

  tearDown(() async {
    StudySession.current = null;
    if (await tmp.exists()) await tmp.delete(recursive: true);
  });

  StudySession session(String p, int n) =>
      StudySession(participant: p, product: 'K1', session: n);

  test('saved photo: same bytes, file name is its logged SHA-256', () async {
    StudySession.current = session('P01', 2); // GUIDED
    final bytes = fakePhoto(1);
    final logged = StudyLog.photoHash(bytes); // what the study log records and sends

    final f = await StudyData.savePhoto(bytes, studyFolder: study);

    expect(f, isNotNull);
    expect(f!.path.replaceAll('\\', '/'),
        endsWith('photos/P01_GUIDED/$logged.jpg'));
    final onDisk = await f.readAsBytes();
    expect(onDisk, bytes, reason: 'no re-encoding');
    expect(sha(onDisk), logged, reason: 'the hash of the file equals the logged hash');
  });

  test('the folder carries the participant and the condition', () async {
    StudySession.current = session('P01', 1); // UNGUIDED first for P01
    final f = await StudyData.savePhoto(fakePhoto(2), studyFolder: study);
    expect(f!.path.replaceAll('\\', '/'), contains('/photos/P01_UNGUIDED/'));
  });

  test('outside study mode nothing is saved', () async {
    StudySession.current = null;
    final f = await StudyData.savePhoto(fakePhoto(3), studyFolder: study);
    expect(f, isNull);
    expect(await study.exists(), isFalse);
  });

  test('saving the same photo twice is harmless (retake / upload path)', () async {
    StudySession.current = session('P01', 2);
    final bytes = fakePhoto(4);
    await StudyData.savePhoto(bytes, studyFolder: study);
    await StudyData.savePhoto(bytes, studyFolder: study);
    final s = await StudyData.summary(study);
    expect(s.photos, 1);
  });

  test('a retaken (undone) photo is kept as well as its replacement', () async {
    StudySession.current = session('P02', 1);
    final first = fakePhoto(5), retake = fakePhoto(6);
    await StudyData.savePhoto(first, studyFolder: study); // taken, then undone
    await StudyData.savePhoto(retake, studyFolder: study); // the retake
    final s = await StudyData.summary(study);
    expect(s.photos, 2);
  });

  test('export zip: log at the root, photos under study/photos, bytes intact', () async {
    StudySession.current = session('P01', 1);
    final a = fakePhoto(10), b = fakePhoto(11);
    await StudyData.savePhoto(a, studyFolder: study);
    StudySession.current = session('P01', 2);
    await StudyData.savePhoto(b, studyFolder: study);
    await File('${study.path}/${StudyData.logName}')
        .writeAsString('{"event":"session_start"}\n');

    final out = Directory('${tmp.path}/out');
    final zip = await StudyData.buildZip(studyFolder: study, outDir: out);
    expect(zip.path.replaceAll('\\', '/'), contains('/out/pqf_study_'));
    expect(zip.path, endsWith('.zip'));
    expect(out.listSync().whereType<File>(), hasLength(1), reason: 'ONE zip');

    final arc = ZipDecoder().decodeBytes(await zip.readAsBytes());
    final names = arc.files.where((f) => f.isFile).map((f) => f.name).toSet();
    expect(names, {
      'study_log.jsonl',
      'study/photos/P01_UNGUIDED/${sha(a)}.jpg',
      'study/photos/P01_GUIDED/${sha(b)}.jpg',
    });
    for (final f in arc.files.where((f) => f.isFile)) {
      if (f.name.startsWith('study/photos/')) {
        final stem = f.name.split('/').last.replaceAll('.jpg', '');
        expect(sha(f.content as List<int>), stem,
            reason: 'file name = sha256 of its bytes after the round trip');
      }
    }
  });

  test('export with nothing on the phone says so instead of making an empty zip', () async {
    expect(() => StudyData.buildZip(studyFolder: study, outDir: Directory('${tmp.path}/o')),
        throwsA(isA<StateError>()));
  });

  test('delete removes the log and every photo', () async {
    StudySession.current = session('P01', 1);
    await StudyData.savePhoto(fakePhoto(20), studyFolder: study);
    await File('${study.path}/${StudyData.logName}').writeAsString('x\n');
    await StudyData.deleteAll(study);
    expect(await study.exists(), isFalse);
    final s = await StudyData.summary(study);
    expect((s.photos, s.hasLog), (0, false));
  });

  // ---- Dry run (prompt 05 step 4): writes a realistic export for the laptop scripts.
  // Opt in with PQF_DRYRUN_OUT=<folder>. One participant, both sessions, fake photos.
  final dryOut = Platform.environment['PQF_DRYRUN_OUT'];
  test('DRY RUN: one participant, both sessions, exported zip', () async {
    final root = Directory('$dryOut');
    final phone = Directory('${root.path}/phone_study');
    if (await phone.exists()) await phone.delete(recursive: true);
    final lines = <String>[];
    final t0 = DateTime.utc(2026, 10, 10, 9, 0);

    String iso(DateTime t) => t.toIso8601String();
    Map<String, dynamic> base(String event, StudySession s, DateTime t) => {
          'event': event,
          'timestamp': iso(t),
          'participant': s.participant,
          'condition': s.condition,
          'product': s.product,
          'session': s.session,
          'times': {
            'session_start': iso(s.startedAt),
            'capture_end': null,
            'video_ready': null,
          },
        };

    // P01: session 1 UNGUIDED, session 2 GUIDED (ABBA). Six fake photos each.
    for (final n in [1, 2]) {
      final s = session('P01', n);
      StudySession.current = s;
      final photos = [for (var i = 0; i < 6; i++) fakePhoto(100 * n + i)];
      for (final p in photos) {
        await StudyData.savePhoto(p, studyFolder: phone);
      }
      final h = photos.map(StudyLog.photoHash).toList();
      final t = t0.add(Duration(minutes: 30 * n));
      lines.add(jsonEncode(base('session_start', s, t)));
      lines.add(jsonEncode({...base('capture_end', s, t.add(const Duration(minutes: 4))),
        'photo_hashes': h}));
      lines.add(jsonEncode({...base('own_picks', s, t.add(const Duration(minutes: 5))),
        'own_picks': {'main': h[0], 'angle1': h[1], 'angle2': h[2], 'detail': h[3]}}));
      lines.add(jsonEncode({...base('batch_result', s, t.add(const Duration(minutes: 6))),
        'photos': [
          for (var i = 0; i < h.length; i++)
            {'hash': h[i], 'tqs': 0.7, 'sqs': 0.6 + i / 100, 'fqs': 0.65, 'role': 'hero_shot',
             'passed': true, 'selected': i < 4}
        ],
        'framework_selection': [
          {'hash': h[0], 'role': 'hero_shot'},
          {'hash': h[1], 'role': 'angle_shot'},
          {'hash': h[2], 'role': 'angle_shot'},
          {'hash': h[3], 'role': 'detail_shot'},
        ],
        'gate': {'certified': true, 'missing': <String>[]},
        'model_version': 'mock',
        'tier': 'free'}));
    }
    StudySession.current = null;
    await File('${phone.path}/${StudyData.logName}')
        .writeAsString('${lines.join('\n')}\n');

    final zip = await StudyData.buildZip(
        studyFolder: phone, outDir: Directory('${root.path}/Downloads_PQF_study'));
    expect(await zip.exists(), isTrue);
    // ignore: avoid_print
    print('DRYRUN_ZIP=${zip.path}');
  }, skip: dryOut == null || dryOut.isEmpty ? 'set PQF_DRYRUN_OUT to run' : false);
}

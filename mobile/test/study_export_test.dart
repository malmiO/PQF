import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/study_session.dart';
import 'package:mobile/services/study_data.dart';
import 'package:mobile/services/study_log.dart';
// ignore: depend_on_referenced_packages
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
// ignore: depend_on_referenced_packages
import 'package:plugin_platform_interface/plugin_platform_interface.dart';

/// Export study data (fixed 2026-10-15).
///
/// The export failed on a fresh install on Android 10: it wrote to /sdcard/Download/PQF/
/// study, which needs WRITE_EXTERNAL_STORAGE granted at run time (the study never asks
/// for it), and a folder left by an earlier install made the mkdir succeed so only the
/// zip itself failed. It now writes to the app's own external folder, which needs no
/// permission and is reachable with `adb pull`.
class _FakePaths extends PathProviderPlatform with MockPlatformInterfaceMixin {
  final String? external;
  final String documents;
  _FakePaths({required this.external, required this.documents});

  @override
  Future<String?> getExternalStoragePath() async => external;

  @override
  Future<String?> getApplicationDocumentsPath() async => documents;
}

Uint8List _photo(int seed) =>
    Uint8List.fromList(List<int>.generate(2000, (i) => (seed * 17 + i * 3) % 251));

void main() {
  late Directory tmp;
  late Directory study;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('pqf_export_test_');
    study = Directory('${tmp.path}/docs/study');
    StudySession.current = null;
  });

  tearDown(() async {
    StudySession.current = null;
    if (await tmp.exists()) await tmp.delete(recursive: true);
  });

  Future<List<Uint8List>> fillStudy({int n = 3}) async {
    StudySession.current =
        StudySession(participant: 'P07', product: 'K1', session: 1);
    final photos = [for (var i = 0; i < n; i++) _photo(i + 1)];
    for (final p in photos) {
      await StudyData.savePhoto(p, studyFolder: study);
    }
    await File('${study.path}/${StudyData.logName}')
        .writeAsString('{"event":"session_start"}\n');
    StudySession.current = null;
    return photos;
  }

  const ext = '/Android/data/com.eclat.pqf/files';

  test('the export folder is the app\'s own external folder, never Download', () async {
    final external = Directory('${tmp.path}/storage/emulated/0$ext');
    await external.create(recursive: true);
    PathProviderPlatform.instance =
        _FakePaths(external: external.path, documents: '${tmp.path}/docs');

    final out = await StudyData.exportFolder();
    expect(out.adbReachable, isTrue);
    expect(out.dir.path.replaceAll('\\', '/'), endsWith('$ext/PQF/study'));
    expect(out.dir.path.toLowerCase(), isNot(contains('download')));
    expect(await out.dir.exists(), isTrue);
    // the probe file is cleaned up
    expect(File('${out.dir.path}/.write_probe').existsSync(), isFalse);
  });

  test('an old Download/PQF/study folder left by an earlier install is not used',
      () async {
    final root = Directory('${tmp.path}/storage/emulated/0');
    await Directory('${root.path}/Download/PQF/study').create(recursive: true);
    await Directory('${root.path}$ext').create(recursive: true);
    PathProviderPlatform.instance = _FakePaths(
        external: '${root.path}$ext', documents: '${tmp.path}/docs');

    await fillStudy();
    final r = await StudyData.export(study);
    expect(r.zip.path.replaceAll('\\', '/'), contains('$ext/PQF/study/'));
    expect(Directory('${root.path}/Download/PQF/study').listSync(), isEmpty);
  });

  test('when the external folder cannot be written, it falls back and says so',
      () async {
    // the "folder" is under a regular file, so creating it fails
    final blocker = File('${tmp.path}/blocker')..writeAsStringSync('x');
    PathProviderPlatform.instance = _FakePaths(
        external: '${blocker.path}/files', documents: '${tmp.path}/docs');

    final out = await StudyData.exportFolder();
    expect(out.adbReachable, isFalse);
    expect(out.dir.path.replaceAll('\\', '/'), endsWith('/docs/export'));
  });

  test('no external storage at all falls back to the private folder', () async {
    PathProviderPlatform.instance =
        _FakePaths(external: null, documents: '${tmp.path}/docs');
    final out = await StudyData.exportFolder();
    expect(out.adbReachable, isFalse);
  });

  test('canWrite is a real write, not an existence check', () async {
    final good = await Directory('${tmp.path}/ok').create();
    expect(await StudyData.canWrite(good), isTrue);
    final file = File('${tmp.path}/notadir')..writeAsStringSync('x');
    expect(await StudyData.canWrite(Directory(file.path)), isFalse);
    expect(await StudyData.canWrite(Directory('${tmp.path}/missing')), isFalse);
  });

  test('export writes ONE complete zip with the log and every photo', () async {
    final external = Directory('${tmp.path}/storage/emulated/0$ext');
    await external.create(recursive: true);
    PathProviderPlatform.instance =
        _FakePaths(external: external.path, documents: '${tmp.path}/docs');
    final photos = await fillStudy(n: 4);

    final r = await StudyData.export(study);
    expect(r.adbReachable, isTrue);
    expect(r.zip.path, endsWith('.zip'));
    expect(r.zip.path.split(RegExp(r'[\\/]')).last, startsWith('pqf_study_P07_'));
    expect(await StudyData.isCompleteZip(r.zip), isTrue);
    expect(r.zip.parent.listSync().whereType<File>(), hasLength(1));

    final arc = ZipDecoder().decodeBytes(await r.zip.readAsBytes());
    final names = arc.files.where((f) => f.isFile).map((f) => f.name).toList();
    expect(names, contains('study_log.jsonl'));
    expect(names.where((n) => n.startsWith('study/photos/P07_')), hasLength(4));
    for (final p in photos) {
      final h = StudyLog.photoHash(p);
      final f = arc.files.firstWhere((f) => f.name.endsWith('$h.jpg'));
      expect(f.content as List<int>, p, reason: 'byte-identical after the export');
    }
  });

  test('isCompleteZip rejects a missing, empty and truncated file', () async {
    expect(await StudyData.isCompleteZip(File('${tmp.path}/none.zip')), isFalse);
    final empty = File('${tmp.path}/empty.zip')..writeAsBytesSync(const []);
    expect(await StudyData.isCompleteZip(empty), isFalse);

    final external = Directory('${tmp.path}/storage/emulated/0$ext');
    await external.create(recursive: true);
    PathProviderPlatform.instance =
        _FakePaths(external: external.path, documents: '${tmp.path}/docs');
    await fillStudy();
    final good = (await StudyData.export(study)).zip;
    final bytes = await good.readAsBytes();
    final cut = File('${tmp.path}/cut.zip')
      ..writeAsBytesSync(bytes.sublist(0, bytes.length - 40));
    expect(await StudyData.isCompleteZip(cut), isFalse);
  });

  test('exporting with nothing on the phone says so', () async {
    final external = Directory('${tmp.path}/storage/emulated/0$ext');
    await external.create(recursive: true);
    PathProviderPlatform.instance =
        _FakePaths(external: external.path, documents: '${tmp.path}/docs');
    expect(() => StudyData.export(study), throwsA(isA<StateError>()));
  });

  test('the export code never writes to Download (comments excluded)', () {
    String code(String path) => File(path)
        .readAsLinesSync()
        .where((l) => !l.trimLeft().startsWith('//'))
        .join(' ');
    final src = code('lib/services/study_data.dart');
    expect(src.contains('/Download'), isFalse);
    expect(src.contains('Download/PQF'), isFalse);
    final screen = code('lib/screens/study_screens.dart');
    expect(screen.contains('Downloads/PQF/study'), isFalse);
    expect(screen.contains('adb pull'), isTrue, reason: 'the message tells how to pull it');
  });
}

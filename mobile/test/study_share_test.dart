import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/study_session.dart';
import 'package:mobile/screens/study_screens.dart';
import 'package:mobile/services/study_data.dart';
import 'package:mobile/services/study_share.dart';
// ignore: depend_on_referenced_packages
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
// ignore: depend_on_referenced_packages
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:share_plus/share_plus.dart';
// ignore: depend_on_referenced_packages
import 'package:share_plus_platform_interface/share_plus_platform_interface.dart';

/// Share the exported study zip (2026-10-15).
///
/// The native side (share_plus) turns the path into a content:// URI from its own
/// FileProvider; what the app controls, and what these tests pin, is WHAT it asks to
/// share: one file, typed application/zip, by path, never a file:// URI or text.
class _FakeSharePlatform extends SharePlatform with MockPlatformInterfaceMixin {
  final calls = <ShareParams>[];

  @override
  Future<ShareResult> share(ShareParams params) async {
    calls.add(params);
    return const ShareResult('', ShareResultStatus.success);
  }
}

class _FakePaths extends PathProviderPlatform with MockPlatformInterfaceMixin {
  final String external;
  final String documents;
  _FakePaths(this.external, this.documents);

  @override
  Future<String?> getExternalStoragePath() async => external;

  @override
  Future<String?> getApplicationDocumentsPath() async => documents;
}

void main() {
  late _FakeSharePlatform fake;

  setUp(() {
    fake = _FakeSharePlatform();
    StudyShare.sharer = SharePlus.custom(fake);
  });

  tearDown(() {
    StudyShare.sharer = null;
    StudySession.current = null;
  });

  test('the share request is one zip file, application/zip, by path', () {
    final zip = File('/storage/emulated/0/Android/data/com.eclat.pqf/files/PQF/study/'
        'pqf_study_P01_20261015_130419.zip');
    final p = StudyShare.paramsFor(zip);
    expect(p.files, hasLength(1));
    final f = p.files!.single;
    expect(f.mimeType, 'application/zip');
    expect(StudyShare.mimeType, 'application/zip');
    expect(f.path, zip.path);
    expect(f.path.split('/').last, 'pqf_study_P01_20261015_130419.zip');
    expect(p.subject, 'PQF study data: pqf_study_P01_20261015_130419.zip');
    // a file:// URI or text would be shared INSTEAD of the file (and file:// crashes on
    // API 24+): neither is set, the plugin builds the content:// URI itself
    expect(p.uri, isNull);
    expect(p.text, isNull);
    expect(f.path.startsWith('file:'), isFalse);
  });

  test('sharing goes through the share sheet exactly as built', () async {
    final zip = File('${Directory.systemTemp.path}/pqf_study_P02_x.zip');
    await StudyShare.share(zip);
    expect(fake.calls, hasLength(1));
    expect(fake.calls.single.files!.single.mimeType, 'application/zip');
    expect(fake.calls.single.files!.single.path, zip.path);
  });

  testWidgets('export opens the share sheet once, then a Share button opens it again',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 2600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    late Directory tmp;
    await tester.runAsync(() async {
      tmp = await Directory.systemTemp.createTemp('pqf_share_test_');
      final ext = Directory('${tmp.path}/storage/emulated/0/Android/data/com.eclat.pqf/files');
      await ext.create(recursive: true);
      PathProviderPlatform.instance = _FakePaths(ext.path, '${tmp.path}/docs');
      StudySession.current =
          StudySession(participant: 'P09', product: 'K1', session: 1);
      final photo = Uint8List.fromList(List<int>.generate(500, (i) => i % 251));
      await StudyData.savePhoto(photo,
          studyFolder: Directory('${tmp.path}/docs/study'));
      await File('${tmp.path}/docs/study/study_log.jsonl')
          .writeAsString('{"event":"session_start"}\n');
      StudySession.current = null;
    });
    addTearDown(() => tmp.delete(recursive: true));

    await tester.pumpWidget(const MaterialApp(home: StudyStartScreen()));
    await tester.pump();
    expect(find.text('Share the last export'), findsNothing,
        reason: 'nothing to share before an export');

    await tester.tap(find.text('Export study data'));
    // real file IO and the fake zone's microtasks interleave: wait, then pump, repeat
    for (var i = 0; i < 200 && fake.calls.isEmpty; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 25)));
      await tester.pump();
    }
    await tester.pump(const Duration(milliseconds: 100));

    // opened once, automatically, with the zip that was just written
    expect(fake.calls, hasLength(1));
    final sent = fake.calls.single.files!.single;
    expect(sent.mimeType, 'application/zip');
    expect(sent.path, endsWith('.zip'));
    expect(sent.path.replaceAll('\\', '/'), contains('/Android/data/com.eclat.pqf/files/PQF/study/'));
    expect(File(sent.path).existsSync(), isTrue, reason: 'the zip stays for adb');

    // and the button is there to do it again
    expect(find.text('Share the last export'), findsOneWidget);
    await tester.tap(find.text('Share the last export'));
    for (var i = 0; i < 40 && fake.calls.length < 2; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 25)));
      await tester.pump();
    }
    expect(fake.calls, hasLength(2));
    expect(fake.calls.last.files!.single.path, sent.path);
  });

  test('the merged release manifest exposes the share provider for com.eclat.pqf',
      () {
    final m = File('build/app/intermediates/merged_manifests/release/'
        'processReleaseManifest/AndroidManifest.xml');
    if (!m.existsSync()) {
      markTestSkipped('no release build output to read');
      return;
    }
    final xml = m.readAsStringSync();
    final i = xml.indexOf('com.eclat.pqf.flutter.share_provider');
    expect(i, greaterThan(0), reason: 'authority is <applicationId>.flutter.share_provider');
    final block = xml.substring(i - 300, i + 400);
    expect(block, contains('ShareFileProvider'));
    expect(block, contains('android:exported="false"'));
    expect(block, contains('android:grantUriPermissions="true"'));
    expect(block, contains('flutter_share_file_paths'));
  });
}

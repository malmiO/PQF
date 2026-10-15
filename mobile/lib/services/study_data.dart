import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive_io.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../models/study_session.dart';
import 'study_log.dart';

/// The study's PHOTOS, kept on the phone for the blind ratings (v1.4.0, prompt 05).
///
/// Study mode already logs codes, hashes, picks and scores. The photographers (O2b)
/// and experts (O3) must also SEE the photos, and research/evaluation/make_blind_packs.py
/// matches them to the log by SHA-256. So the saved file must be byte-identical to what
/// was hashed and sent: no re-encoding, no resizing, no metadata stripping.
///
/// Layout under the app's private folder (the same `study/` folder as study_log.jsonl):
///   study/study_log.jsonl
///   study/photos/<participant>_<condition>/<sha256>.jpg
///
/// Everything here is a no-op outside study mode, and nothing here throws: a storage
/// problem must never stop a participant's session (the same rule as StudyLog.log).
class StudyData {
  static const logName = 'study_log.jsonl';
  static const photosDir = 'photos';

  /// The app's private study folder. [override] is for tests.
  static Future<Directory> studyDir([Directory? override]) async {
    if (override != null) return override;
    return Directory('${(await getApplicationDocumentsDirectory()).path}/study');
  }

  /// The photo's path relative to the study folder.
  static String photoRelPath(String participant, String condition, String hash) =>
      '$photosDir/${participant}_$condition/$hash.jpg';

  /// Saves one captured photo, in study mode only. Returns the file, or null outside
  /// study mode or on a storage error. Saving the same bytes twice is harmless.
  static Future<File?> savePhoto(
    Uint8List bytes, {
    StudySession? session,
    Directory? studyFolder,
  }) async {
    final s = session ?? StudySession.current;
    if (s == null) return null;
    try {
      final hash = StudyLog.photoHash(bytes);
      final root = await studyDir(studyFolder);
      final f = File('${root.path}/${photoRelPath(s.participant, s.condition, hash)}');
      if (await f.exists() && await f.length() == bytes.length) return f;
      await f.parent.create(recursive: true);
      await f.writeAsBytes(bytes, flush: true);
      return f;
    } catch (e) {
      debugPrint('[study] saving a photo failed: $e');
      return null;
    }
  }

  /// How much study data is on the phone.
  static Future<({int photos, int bytes, bool hasLog})> summary(
      [Directory? studyFolder]) async {
    // Never throws: this is read when the researcher screen opens, and a storage
    // problem must not stop a session (the same rule as StudyLog.log).
    try {
      final root = await studyDir(studyFolder);
      var photos = 0, bytes = 0;
      final p = Directory('${root.path}/$photosDir');
      if (await p.exists()) {
        await for (final e in p.list(recursive: true, followLinks: false)) {
          if (e is File) {
            photos++;
            bytes += await e.length();
          }
        }
      }
      return (
        photos: photos,
        bytes: bytes,
        hasLog: await File('${root.path}/$logName').exists(),
      );
    } catch (e) {
      debugPrint('[study] reading the study data summary failed: $e');
      return (photos: 0, bytes: 0, hasLog: false);
    }
  }

  /// Builds ONE zip in [outDir] holding study_log.jsonl and study/photos/..., laid out
  /// so that unzipping gives `study_log.jsonl` and `study/photos/...` (what
  /// make_blind_packs.py's --log and --photos expect). Throws StateError if there is
  /// nothing to export.
  static Future<File> buildZip({
    Directory? studyFolder,
    required Directory outDir,
    DateTime? now,
  }) async {
    final root = await studyDir(studyFolder);
    final log = File('${root.path}/$logName');
    final photos = Directory('${root.path}/$photosDir');
    final files = <File>[];
    if (await photos.exists()) {
      await for (final e in photos.list(recursive: true, followLinks: false)) {
        if (e is File) files.add(e);
      }
    }
    final hasLog = await log.exists();
    if (!hasLog && files.isEmpty) {
      throw StateError('There is no study data on this phone yet.');
    }
    files.sort((a, b) => a.path.compareTo(b.path));

    // Participant id(s) present on the phone, from the photo folders
    // (<participant>_<condition>), so the zip name says whose data it is.
    final participants = <String>{};
    for (final f in files) {
      final parent = Directory(f.parent.path).path.split(RegExp(r'[\\/]')).last;
      final pid = parent.split('_').first;
      if (pid.isNotEmpty) participants.add(pid);
    }
    final who = participants.isEmpty
        ? 'unknown'
        : (participants.length == 1
            ? participants.first
            : (participants.toList()..sort()).take(4).join('-'));

    await outDir.create(recursive: true);
    final t = (now ?? DateTime.now());
    String two(int v) => v.toString().padLeft(2, '0');
    final stamp = '${t.year}${two(t.month)}${two(t.day)}_'
        '${two(t.hour)}${two(t.minute)}${two(t.second)}';
    final zip = File('${outDir.path}/pqf_study_${who}_$stamp.zip');

    final enc = ZipFileEncoder()..create(zip.path);
    try {
      if (hasLog) await enc.addFile(log, logName);
      for (final f in files) {
        final rel = f.path
            .substring(root.path.length)
            .replaceAll('\\', '/')
            .replaceFirst(RegExp(r'^/+'), '');
        await enc.addFile(f, 'study/$rel');
      }
    } finally {
      await enc.close();
    }
    return zip;
  }

  /// Where the export is written (fixed 2026-10-15).
  ///
  /// The app's OWN folder on external storage,
  ///   /storage/emulated/0/Android/data/com.eclat.pqf/files/PQF/study
  /// which needs no storage permission on any Android version, and which the researcher
  /// can `adb pull` (also reachable as /sdcard/Android/data/...). It is probed with a real
  /// write, not only a mkdir.
  ///
  /// The previous version wrote to /sdcard/Download/PQF/study. On Android 10 with
  /// scoped storage that folder is writable only once WRITE_EXTERNAL_STORAGE has been
  /// granted at run time, and the app never asks for it for the study. A folder left by
  /// an earlier install made `create()` succeed (it already existed), so the failure only
  /// appeared when the zip file itself was opened for writing: "Export failed".
  ///
  /// [adbReachable] is false only in the last resort (the app's private documents
  /// folder, which a release build does not expose to adb): the caller must say so.
  static Future<({Directory dir, bool adbReachable})> exportFolder() async {
    try {
      final ext = await getExternalStorageDirectory();
      if (ext != null) {
        final d = Directory('${ext.path}/PQF/study');
        await d.create(recursive: true);
        if (await canWrite(d)) return (dir: d, adbReachable: true);
      }
    } catch (e) {
      debugPrint('[study] app external folder not writable: $e');
    }
    final base = await getApplicationDocumentsDirectory();
    final d = Directory('${base.path}/export');
    await d.create(recursive: true);
    return (dir: d, adbReachable: false);
  }

  /// True when a file can really be created and removed in [dir].
  static Future<bool> canWrite(Directory dir) async {
    try {
      final probe = File('${dir.path}/.write_probe');
      await probe.writeAsBytes(const [0x50, 0x51, 0x46], flush: true);
      await probe.delete();
      return true;
    } catch (_) {
      return false;
    }
  }

  /// A cheap completeness check: a finished zip ends with the end-of-central-directory
  /// record (PK 05 06). Catches a half-written file without reading all the photos.
  static Future<bool> isCompleteZip(File zip) async {
    try {
      final len = await zip.length();
      if (len < 22) return false;
      final raf = await zip.open();
      try {
        await raf.setPosition(len - 22);
        final tail = await raf.read(22);
        return tail.length == 22 &&
            tail[0] == 0x50 && tail[1] == 0x4B && tail[2] == 0x05 && tail[3] == 0x06;
      } finally {
        await raf.close();
      }
    } catch (_) {
      return false;
    }
  }

  /// Exports one zip and checks that it was written completely. Returns the zip and
  /// whether it is in a folder `adb pull` can reach (see [exportFolder]).
  /// [outDir] is for tests; production passes nothing.
  static Future<({File zip, bool adbReachable})> export(
      [Directory? studyFolder, Directory? outDir]) async {
    var reachable = true;
    Directory dir;
    if (outDir != null) {
      dir = outDir;
    } else {
      final out = await exportFolder();
      dir = out.dir;
      reachable = out.adbReachable;
    }
    final zip = await buildZip(studyFolder: studyFolder, outDir: dir);
    if (!await isCompleteZip(zip)) {
      throw StateError('The export zip was not written completely: ${zip.path}');
    }
    return (zip: zip, adbReachable: reachable);
  }

  /// Removes the study log and every saved photo from this phone.
  static Future<void> deleteAll([Directory? studyFolder]) async {
    final root = await studyDir(studyFolder);
    if (await root.exists()) await root.delete(recursive: true);
  }
}

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:gal/gal.dart';
import 'package:image/image.dart' as img;
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../services/pqf_api.dart';

/// Saves a finished product (the certified set, its video, caption and
/// results) to the phone.
///
/// WHY THIS OUTPUT EXISTS. Expert consultation established that sellers
/// repeatedly need to send individual images to customers during a conversation,
/// and re-shoot because they have nothing ready. A set that lives only inside
/// the app does not solve that. The images must end up somewhere the seller can
/// reach from WhatsApp or Instagram.
///
/// WHY FILES ARE NAMED BY ROLE. The role is what makes the set useful. A seller
/// scrolling their gallery can tell the main shot from a detail shot without
/// opening anything, which is the difference between a usable set and four
/// similar looking files.
///
/// WHY ONLY THE SET IS SAVED. Saving rejected or unused images alongside the set
/// would undermine the point of certifying it.
class ImageSaver {
  /// Saves everything for one finished product into
  /// `PQF/<name>_<yyyyMMdd_HHmm>/`: ONLY the set photos (1_main.jpg,
  /// 2_angle.jpg, ...), promo_video.mp4, caption.txt and results.json
  /// (2026-10-06).
  ///
  /// Photos and the video go through the gallery (`Pictures/PQF/<folder>`).
  /// The two text files are written next to them where Android allows it (up
  /// to Android 10, with the storage permission the gallery step asks for); on
  /// newer Android they go to the app's own folder, and the outcome says where.
  /// Gallery refused or unavailable: the files are offered through the share
  /// sheet instead, which needs no permission.
  static Future<PackageSaveOutcome> saveProduct({
    required ProductDraft draft,
    required List<SetPhoto> set,
    required String videoPath,
    required VideoPlan plan,
  }) async {
    final now = DateTime.now();
    final folder = '${_folderName(draft.name)}_${_stamp(now)}';
    final album = 'PQF/$folder';

    // Stage every file under its final name; gal keeps the file name.
    final List<File> photos = [];
    late final File video;
    late final File caption;
    late final File results;
    try {
      final tmp = Directory(
          '${(await getTemporaryDirectory()).path}/pqf_save/$folder');
      await tmp.create(recursive: true);
      final setJson = <Map<String, dynamic>>[];
      for (var i = 0; i < set.length; i++) {
        final name = '${i + 1}_${set[i].roleSlug}.jpg';
        final f = File('${tmp.path}/$name');
        await f.writeAsBytes(_cropForSave(set[i].bytes), flush: true);
        photos.add(f);
        setJson.add({'file': name, 'role': set[i].role, 'fqs': set[i].fqs});
      }
      video = await File(videoPath).copy('${tmp.path}/promo_video.mp4');
      caption = File('${tmp.path}/caption.txt');
      await caption.writeAsString(plan.caption, flush: true);
      results = File('${tmp.path}/results.json');
      await results.writeAsString(
        const JsonEncoder.withIndent('  ').convert({
          'product': draft.toJson(),
          'saved_at': now.toIso8601String(),
          'certified': true,
          'set': setJson,
          'plan': plan.raw,
        }),
        flush: true,
      );
    } catch (e) {
      debugPrint('Preparing the files to save failed. $e');
      return PackageSaveOutcome(
          folder: album, error: 'Could not prepare the files to save. $e');
    }
    final all = [...photos, video, caption, results];

    try {
      final hasAccess = await Gal.hasAccess(toAlbum: true);
      if (!hasAccess && !await Gal.requestAccess(toAlbum: true)) {
        return await _sharePackage(all, album,
            reason: 'Permission to save to your photos was not granted.');
      }
      for (final p in photos) {
        await Gal.putImage(p.path, album: album);
      }
      await Gal.putVideo(video.path, album: album);
    } catch (e) {
      debugPrint('Gallery save failed, falling back to share. $e');
      return _sharePackage(all, album,
          reason: 'Saving to your photos did not work on this phone.');
    }

    // The text files: into the same folder if Android allows it.
    try {
      final dir = Directory('${await _sharedRoot()}/Pictures/$album');
      await dir.create(recursive: true);
      await caption.copy('${dir.path}/caption.txt');
      await results.copy('${dir.path}/results.json');
      return PackageSaveOutcome(folder: album, saved: true);
    } catch (e) {
      debugPrint('Shared folder not writable for text files ($e). '
          'Using the app folder.');
    }
    try {
      final base = await getExternalStorageDirectory() ??
          await getApplicationDocumentsDirectory();
      final dir = Directory('${base.path}/$album');
      await dir.create(recursive: true);
      await caption.copy('${dir.path}/caption.txt');
      await results.copy('${dir.path}/results.json');
      return PackageSaveOutcome(
        folder: album,
        saved: true,
        note: 'This Android version keeps caption.txt and results.json out of '
            'the photo folder. They are in ${dir.path}.',
      );
    } catch (e) {
      return PackageSaveOutcome(
        folder: album,
        error: 'The photos and video were saved, but caption.txt and '
            'results.json could not be. $e',
      );
    }
  }

  static Future<PackageSaveOutcome> _sharePackage(
    List<File> files,
    String album, {
    required String reason,
  }) async {
    try {
      await SharePlus.instance.share(ShareParams(
          files: files.map((f) => XFile(f.path)).toList(),
          subject: 'Product photos and video'));
      return PackageSaveOutcome(folder: album, shared: true, error: reason);
    } catch (e) {
      return PackageSaveOutcome(
          folder: album, error: '$reason Sharing did not work either. $e');
    }
  }

  /// The root of shared storage (/storage/emulated/0), from the app's own
  /// external folder, which sits under `<root>/Android/data/<package>/files`.
  static Future<String> _sharedRoot() async {
    final ext = await getExternalStorageDirectory();
    if (ext == null) throw const FileSystemException('No external storage.');
    final i = ext.path.indexOf('/Android/');
    if (i < 0) throw FileSystemException('Unexpected path', ext.path);
    return ext.path.substring(0, i);
  }

  /// The product name as a folder name: letters and digits kept, case kept,
  /// everything else becomes "_".
  static String _folderName(String s) {
    final cleaned = s
        .trim()
        .replaceAll(RegExp(r'[^A-Za-z0-9]+'), '_')
        .replaceAll(RegExp(r'^_+|_+$'), '');
    return cleaned.isEmpty ? 'Product' : cleaned;
  }

  /// yyyyMMdd_HHmm
  static String _stamp(DateTime t) {
    String two(int v) => v.toString().padLeft(2, '0');
    return '${t.year}${two(t.month)}${two(t.day)}_${two(t.hour)}${two(t.minute)}';
  }

  /// Centre crop the SAVED copy to 4:5 (full width) when the photo is taller
  /// than 4:5, so the saved file is exactly the region the framework scored.
  /// The server centre crops the captured photo to 4:5 before scoring, so an
  /// uncropped saved file would show strips the framework never judged.
  ///
  /// This is applied ONLY to the copy written to the gallery or share sheet.
  /// The bytes sent to /score and /batch are never cropped or re-encoded.
  static Uint8List _cropForSave(Uint8List bytes) {
    try {
      final decoded = img.decodeImage(bytes);
      if (decoded == null) return bytes;
      final w = decoded.width;
      final h = decoded.height;
      // 4:5 means width / height = 0.8. Only act when the photo is taller.
      if (w / h >= 0.8) return bytes;
      final newH = (w * 5 / 4).round();
      if (newH >= h) return bytes;
      final top = (h - newH) ~/ 2;
      final cropped =
          img.copyCrop(decoded, x: 0, y: top, width: w, height: newH);
      return Uint8List.fromList(img.encodeJpg(cropped, quality: 95));
    } catch (e) {
      debugPrint('Save crop failed, saving the original. $e');
      return bytes;
    }
  }

}

/// What happened when a finished product was saved.
class PackageSaveOutcome {
  /// `PQF/<name>_<yyyyMMdd_HHmm>`
  final String folder;

  /// Everything is on the phone.
  final bool saved;

  /// Not saved, but the share sheet was opened with the files instead.
  final bool shared;

  /// Where some files went instead, when that differs from [folder].
  final String? note;

  /// Why saving failed, in plain words.
  final String? error;

  PackageSaveOutcome({
    required this.folder,
    this.saved = false,
    this.shared = false,
    this.note,
    this.error,
  });

  bool get ok => saved && error == null;
}

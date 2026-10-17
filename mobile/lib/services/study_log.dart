import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import '../app_info.dart';
import '../models/study_session.dart';
import 'pqf_api.dart';
import 'study_data.dart';

/// One JSON line per study event, written to the app's folder AND sent to
/// POST /study/log (v1.1.0, Step 7). The local file is the copy that survives a
/// lost connection. Photos are identified by their SHA-256, never sent.
class StudyLog {
  static String photoHash(Uint8List bytes) => sha256.convert(bytes).toString();

  static String _now() => DateTime.now().toUtc().toIso8601String();

  static Map<String, dynamic> _times(StudySession s) => {
        'session_start': s.startedAt.toIso8601String(),
        'capture_end': s.captureEndAt?.toIso8601String(),
        'video_ready': s.videoReadyAt?.toIso8601String(),
      };

  /// Writes and sends one event for the current session. Does nothing outside
  /// study mode. Never throws: a logging problem must not stop the session.
  static Future<void> log(String event, [Map<String, dynamic> extra = const {}]) async {
    final s = StudySession.current;
    if (s == null) return;
    final entry = <String, dynamic>{
      'event': event,
      'timestamp': _now(),
      'participant': s.participant,
      'condition': s.condition,
      'product': s.product,
      'session': s.session,
      'times': _times(s),
      ...extra,
    };
    final line = jsonEncode(entry);
    try {
      final dir = Directory('${(await getApplicationDocumentsDirectory()).path}/study');
      await dir.create(recursive: true);
      await File('${dir.path}/study_log.jsonl')
          .writeAsString('$line\n', mode: FileMode.append, flush: true);
    } catch (e) {
      debugPrint('[study] local log failed: $e');
    }
    try {
      final r = await http
          .post(Uri.parse('${ApiConfig.baseUrl}/study/log'),
              headers: {'Content-Type': 'application/json', ...ApiConfig.authHeaders},
              body: line)
          .timeout(const Duration(seconds: 10));
      if (r.statusCode != 200) {
        final b = r.body.length > 300 ? r.body.substring(0, 300) : r.body;
        debugPrint('[study] POST /study/log failed: status=${r.statusCode} body=$b');
      }
    } catch (e) {
      debugPrint('[study] POST /study/log failed: $e');
    }
  }

  /// The phone's model, read once (Android). Empty if it cannot be read.
  static String? _deviceModel;
  static Future<String> _device() async {
    if (_deviceModel != null) return _deviceModel!;
    try {
      if (Platform.isAndroid) {
        final a = await DeviceInfoPlugin().androidInfo;
        _deviceModel = '${a.manufacturer} ${a.model} (Android ${a.version.release}, '
            'API ${a.version.sdkInt})';
      } else {
        _deviceModel = Platform.operatingSystem;
      }
    } catch (_) {
      _deviceModel = '';
    }
    return _deviceModel!;
  }

  /// Session start: records the group, device, app build/version and the
  /// counterbalanced condition order (and, for session 2, same-product y/n).
  static Future<void> sessionStart(StudySession s) async {
    return log('session_start', {
      'group': s.group,
      'device_model': await _device(),
      'app_version': AppInfo.version,
      'app_build': AppInfo.build,
      'apk_version': '${AppInfo.version}+${AppInfo.build}',
      'condition_order': s.conditionOrder,
      if (s.session == 2 && s.sameProductAsFirst != null)
        'same_product_as_first': s.sameProductAsFirst,
    });
  }

  /// Pixel size and EXIF orientation of a JPEG, best-effort (null on failure).
  static ({int? width, int? height, int? exif}) imageMeta(Uint8List bytes) {
    try {
      final d = img.decodeImage(bytes);
      if (d == null) return (width: null, height: null, exif: null);
      int? orient;
      try {
        orient = d.exif.imageIfd.hasOrientation ? d.exif.imageIfd.orientation : null;
      } catch (_) {
        orient = null;
      }
      return (width: d.width, height: d.height, exif: orient);
    } catch (_) {
      return (width: null, height: null, exif: null);
    }
  }

  /// One photo saved: logged the moment it is written, with its provenance.
  static Future<void> photoCaptured({
    required Uint8List bytes,
    required String shotRequested, // main | angle1 | angle2 | detail
    String? retakeOf, // hash of the photo this one replaces, or null
    required String source, // in_app | upload
    int? width,
    int? height,
    int? exifOrientation,
  }) =>
      log('photo_captured', {
        'hash': photoHash(bytes),
        'shot_requested': shotRequested,
        'retake_of': retakeOf,
        'source': source,
        'width': width,
        'height': height,
        'exif_orientation': exifOrientation,
      });

  /// The most /guidance round trips one capture_end can carry (the server accepts 300).
  static const int maxGuidanceMs = 300;

  /// End of capture: the hashes of the photos taken, and how long each SUCCESSFUL
  /// /guidance call took (ms, request sent to response parsed). Empty in the unguided
  /// condition, which makes no call. Past [maxGuidanceMs] only the latest are kept.
  static Future<void> captureEnd(List<Uint8List> photos, List<int> guidanceMs) {
    final ms = [for (final v in guidanceMs) v.clamp(0, 60000)];
    final kept = ms.length > maxGuidanceMs ? ms.sublist(ms.length - maxGuidanceMs) : ms;
    return log('capture_end', {
      'photo_hashes': photos.map(photoHash).toList(),
      'guidance_ms': kept,
    });
  }

  /// The participant's own picks: slot (main, angle1, angle2, detail) -> photo.
  static Future<void> ownPicks(Map<String, Uint8List> picks) =>
      log('own_picks', {'own_picks': picks.map((k, v) => MapEntry(k, photoHash(v)))});

  /// A /batch result: every photo's scores and role, the framework's selection,
  /// and the gate result.
  static Future<void> batchResult(List<Uint8List> images, BatchResult r) async {
    // Every photo in a logged batch must also exist as a file (the upload path does
    // not go through the camera). Photos already saved at capture are skipped.
    await Future.wait(images.map((b) => StudyData.savePhoto(b)));
    final hashes = images.map(photoHash).toList();
    String h(int i) => (i >= 0 && i < hashes.length) ? hashes[i] : '';
    final selected = {for (final p in r.images) p.index: p.selected};
    return log('batch_result', {
      'photos': [
        for (final s in r.selected)
          if (h(s.index).isNotEmpty)
            {
              'hash': h(s.index),
              'tqs': s.tqs,
              'sqs': s.sqs,
              'fqs': s.fqs,
              'role': s.role,
              'passed': s.passed,
              'selected': selected[s.index] ?? false,
            }
      ],
      'framework_selection': [
        for (final p in r.setPhotos)
          if (h(p.index).isNotEmpty) {'hash': h(p.index), 'role': p.role}
      ],
      'gate': {
        'certified': r.certified,
        'missing': [for (final m in r.missing) m.role],
      },
      // Which model answered and on which tier. Omitted when the server did not
      // say (an older server), because the log refuses an empty value.
      if (r.modelVersion.isNotEmpty) 'model_version': r.modelVersion,
      if (r.tier.isNotEmpty) 'tier': r.tier,
    });
  }
}

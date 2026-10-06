import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import '../models/study_session.dart';
import 'pqf_api.dart';

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

  /// The participant's own picks: slot (main, angle1, angle2, detail) -> photo.
  static Future<void> ownPicks(Map<String, Uint8List> picks) =>
      log('own_picks', {'own_picks': picks.map((k, v) => MapEntry(k, photoHash(v)))});

  /// A /batch result: every photo's scores and role, the framework's selection,
  /// and the gate result.
  static Future<void> batchResult(List<Uint8List> images, BatchResult r) {
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
    });
  }
}

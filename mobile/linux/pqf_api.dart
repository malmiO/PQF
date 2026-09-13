import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

import '../config/api_config.dart';
export '../config/api_config.dart';

/// One criterion, as returned by the API.
class CriterionResult {
  final String name;
  final double score;
  final double weight;
  final bool? passed;

  CriterionResult({
    required this.name,
    required this.score,
    required this.weight,
    this.passed,
  });

  factory CriterionResult.fromJson(Map<String, dynamic> j) => CriterionResult(
        name: j['name'] as String,
        score: (j['score'] as num).toDouble(),
        weight: (j['weight'] as num).toDouble(),
        passed: j['passed'] as bool?,
      );

  /// Human readable label. The user never sees the internal criterion names.
  String get label {
    switch (name) {
      case 'sharpness':
        return 'Focus';
      case 'exposure':
        return 'Light';
      case 'background':
        return 'Background';
      default:
        return name;
    }
  }
}

/// Response from the fast pre capture check.
class GuidanceResult {
  final bool ready;
  final List<CriterionResult> checks;
  final List<String> feedback;
  final int elapsedMs;

  GuidanceResult({
    required this.ready,
    required this.checks,
    required this.feedback,
    required this.elapsedMs,
  });

  factory GuidanceResult.fromJson(Map<String, dynamic> j) => GuidanceResult(
        ready: j['ready'] as bool,
        checks: (j['checks'] as List)
            .map((c) => CriterionResult.fromJson(c as Map<String, dynamic>))
            .toList(),
        feedback: (j['feedback'] as List).map((f) => f as String).toList(),
        elapsedMs: j['elapsed_ms'] as int,
      );

  /// The single instruction to show. Showing every failing criterion at once
  /// overwhelms a non expert, so only the first is surfaced.
  String? get primaryInstruction => feedback.isEmpty ? null : feedback.first;

  static GuidanceResult empty() => GuidanceResult(
        ready: false,
        checks: const [],
        feedback: const [],
        elapsedMs: 0,
      );
}

/// One image in a certified or rejected batch.
class BatchImageResult {
  final int index;
  final double fqs;
  final String role;
  final bool passed;

  BatchImageResult({
    required this.index,
    required this.fqs,
    required this.role,
    required this.passed,
  });

  factory BatchImageResult.fromJson(Map<String, dynamic> j) => BatchImageResult(
        index: j['index'] as int,
        fqs: (j['fqs'] as num).toDouble(),
        role: j['role'] as String,
        passed: j['passed'] as bool,
      );

  String get roleLabel {
    switch (role) {
      case 'hero_shot':
        return 'Main shot';
      case 'angle_shot':
        return 'Angle';
      case 'detail_shot':
        return 'Detail';
      default:
        return 'Not used';
    }
  }
}

/// Result of scoring a whole capture batch.
class BatchResult {
  final bool certified;
  final List<BatchImageResult> selected;
  final Map<String, List<String>> roleSets;
  final Map<String, dynamic>? recapture;

  BatchResult({
    required this.certified,
    required this.selected,
    required this.roleSets,
    this.recapture,
  });

  factory BatchResult.fromJson(Map<String, dynamic> j) {
    final rs = <String, List<String>>{};
    (j['role_sets'] as Map<String, dynamic>).forEach((k, v) {
      rs[k] = (v as List).map((e) => e.toString()).toList();
    });
    return BatchResult(
      certified: j['certified'] as bool,
      selected: (j['selected'] as List)
          .map((s) => BatchImageResult.fromJson(s as Map<String, dynamic>))
          .toList(),
      roleSets: rs,
      recapture: j['recapture'] as Map<String, dynamic>?,
    );
  }

  /// What the user is told when the set is not good enough yet.
  String get recaptureInstruction =>
      recapture?['instruction'] as String? ?? 'Capture a few more images.';
}

/// Client for the PQF API.
class PqfApi {
  final http.Client _client = http.Client();

  /// Fast pre capture check. No semantic model call, so this is free and quick.
  /// Returns null on any failure, because a dropped guidance frame should never
  /// interrupt the camera.
  Future<GuidanceResult?> guidance(Uint8List jpegBytes) async {
    try {
      final req = http.MultipartRequest(
        'POST',
        Uri.parse('${ApiConfig.baseUrl}/guidance'),
      )..files.add(http.MultipartFile.fromBytes(
          'file',
          jpegBytes,
          filename: 'frame.jpg',
        ));

      final streamed = await req.send().timeout(ApiConfig.guidanceTimeout);
      if (streamed.statusCode != 200) return null;
      final body = await streamed.stream.bytesToString();
      return GuidanceResult.fromJson(jsonDecode(body) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  /// Score a whole capture batch, select the best set, and run the quality gate.
  Future<BatchResult> batch(List<Uint8List> images) async {
    final req = http.MultipartRequest(
      'POST',
      Uri.parse('${ApiConfig.baseUrl}/batch'),
    );
    for (var i = 0; i < images.length; i++) {
      req.files.add(http.MultipartFile.fromBytes(
        'files',
        images[i],
        filename: 'capture_$i.jpg',
      ));
    }
    final streamed = await req.send().timeout(ApiConfig.batchTimeout);
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode != 200) {
      throw Exception('Scoring failed (${streamed.statusCode}). $body');
    }
    return BatchResult.fromJson(jsonDecode(body) as Map<String, dynamic>);
  }

  /// Confirms the server is reachable before the user starts capturing.
  Future<bool> health() async {
    try {
      final r = await _client
          .get(Uri.parse('${ApiConfig.baseUrl}/health'))
          .timeout(const Duration(seconds: 6));
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}

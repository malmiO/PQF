import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'dart:io';

import '../config/api_config.dart';
import '../models/api_result.dart';
export '../config/api_config.dart';
export '../models/api_result.dart';

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
///
/// Every method returns an [ApiResult] rather than throwing, so a caller never
/// has to interpret an exception, and the user never sees one.
class PqfApi {
  final http.Client _client = http.Client();

  /// Turns any thrown object into a classified, user readable failure.
  ApiFailure _classify(Object e) {
    final text = e.toString();
    if (e is SocketException || text.contains('SocketException') ||
        text.contains('Connection refused') || text.contains('Failed host lookup')) {
      return ApiFailure.unreachable(text);
    }
    if (e is HttpException) return ApiFailure.server(0, text);
    if (text.contains('TimeoutException') || text.contains('timed out')) {
      return ApiFailure.timeout(text);
    }
    return ApiFailure.unknown(text);
  }

  /// Reads a failing response body and works out what actually went wrong.
  /// A quota failure is worth distinguishing, because retrying is pointless and
  /// telling the user to wait until tomorrow is more useful than "try again".
  ApiFailure _fromResponse(int status, String body) {
    final lower = body.toLowerCase();
    if (status == 429 || lower.contains('resource_exhausted') ||
        lower.contains('quota')) {
      return ApiFailure.quota(body);
    }
    if (status == 400 || status == 415 || status == 422) {
      return ApiFailure.badImage(body);
    }
    return ApiFailure.server(status, body);
  }

  /// Fast pre capture check. No semantic model call, so this is free and quick.
  ///
  /// A dropped guidance frame is not an error worth reporting. The camera must
  /// keep working, so failures here are returned quietly and the caller simply
  /// keeps the previous reading.
  Future<ApiResult<GuidanceResult>> guidance(Uint8List jpegBytes) async {
    try {
      final req = http.MultipartRequest(
        'POST',
        Uri.parse('${ApiConfig.baseUrl}/guidance'),
      )..files.add(http.MultipartFile.fromBytes(
          'file',
          jpegBytes,
          filename: 'frame.jpg',
          // Without this the part is sent as application/octet-stream, which a
          // server that validates the declared type will reject.
          contentType: MediaType('image', 'jpeg'),
        ));

      final streamed = await req.send().timeout(ApiConfig.guidanceTimeout);
      final body = await streamed.stream.bytesToString();
      if (streamed.statusCode != 200) {
        return ApiResult.failure(_fromResponse(streamed.statusCode, body));
      }
      return ApiResult.success(
          GuidanceResult.fromJson(jsonDecode(body) as Map<String, dynamic>));
    } catch (e) {
      return ApiResult.failure(_classify(e));
    }
  }

  /// Score a whole capture batch, select the best set, and run the quality gate.
  Future<ApiResult<BatchResult>> batch(List<Uint8List> images) async {
    if (images.isEmpty) {
      return ApiResult.failure(ApiFailure.badImage('No images to send.'));
    }
    try {
      final req = http.MultipartRequest(
        'POST',
        Uri.parse('${ApiConfig.baseUrl}/batch'),
      );
      for (var i = 0; i < images.length; i++) {
        req.files.add(http.MultipartFile.fromBytes(
          'files',
          images[i],
          filename: 'capture_$i.jpg',
          contentType: MediaType('image', 'jpeg'),
        ));
      }
      final streamed = await req.send().timeout(ApiConfig.batchTimeout);
      final body = await streamed.stream.bytesToString();
      if (streamed.statusCode != 200) {
        return ApiResult.failure(_fromResponse(streamed.statusCode, body));
      }
      return ApiResult.success(
          BatchResult.fromJson(jsonDecode(body) as Map<String, dynamic>));
    } catch (e) {
      return ApiResult.failure(_classify(e));
    }
  }

  /// Confirms the server is reachable before the user starts capturing.
  Future<ApiResult<bool>> health() async {
    try {
      final r = await _client
          .get(Uri.parse('${ApiConfig.baseUrl}/health'))
          .timeout(const Duration(seconds: 6));
      if (r.statusCode != 200) {
        return ApiResult.failure(_fromResponse(r.statusCode, r.body));
      }
      return const ApiResult.success(true);
    } catch (e) {
      return ApiResult.failure(_classify(e));
    }
  }
}

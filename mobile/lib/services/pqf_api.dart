import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'dart:io';

import '../config/api_config.dart';
import '../models/api_result.dart';
import '../models/product_draft.dart';
export '../config/api_config.dart';
export '../models/api_result.dart';
export '../models/product_draft.dart';

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
      case 'framing':
        return 'Framing';
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

  /// +1 means "raise the brightness", -1 "lower it", 0 no change. The app
  /// applies this as camera exposure compensation, the step a photographer
  /// does by hand when a grey lightbox background needs more light.
  final int exposureHint;

  /// Auto zoom (v1.1.0): the factor to apply on top of the current zoom so the
  /// product reaches its target size. 1.0 means leave the zoom as it is.
  final double zoomHint;

  GuidanceResult({
    required this.ready,
    required this.checks,
    required this.feedback,
    required this.elapsedMs,
    this.exposureHint = 0,
    this.zoomHint = 1.0,
  });

  factory GuidanceResult.fromJson(Map<String, dynamic> j) => GuidanceResult(
        ready: j['ready'] as bool,
        checks: (j['checks'] as List)
            .map((c) => CriterionResult.fromJson(c as Map<String, dynamic>))
            .toList(),
        feedback: (j['feedback'] as List).map((f) => f as String).toList(),
        elapsedMs: j['elapsed_ms'] as int,
        exposureHint: (j['exposure_hint'] as num?)?.toInt() ?? 0,
        zoomHint: (j['zoom_hint'] as num?)?.toDouble() ?? 1.0,
      );

  /// The order fixes are asked for (v1.1.0): framing first (where the product
  /// sits and how big it is), then focus, light and background.
  static const instructionOrder = ['framing', 'sharpness', 'exposure', 'background'];

  /// The single instruction to show. Showing every failing criterion at once
  /// overwhelms a non expert, so only the most important one is surfaced.
  /// The server lists one feedback line per failing check, in the order of
  /// [checks]; this picks the line of the highest priority failing check.
  String? get primaryInstruction {
    if (feedback.isEmpty) return null;
    final failing = [for (final c in checks) if (c.passed == false) c.name];
    if (failing.length != feedback.length) return feedback.first;
    for (final name in instructionOrder) {
      final i = failing.indexOf(name);
      if (i >= 0) return feedback[i];
    }
    return feedback.first;
  }

  /// Whether the framing check passed (null before the first reading).
  bool? get framingOk {
    for (final c in checks) {
      if (c.name == 'framing') return c.passed;
    }
    return null;
  }

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
  final double tqs;
  final double sqs;
  final String role;
  final bool passed;
  final String reason;
  final String weakest;

  BatchImageResult({
    required this.index,
    required this.fqs,
    required this.tqs,
    required this.sqs,
    required this.role,
    required this.passed,
    required this.reason,
    required this.weakest,
  });

  factory BatchImageResult.fromJson(Map<String, dynamic> j) => BatchImageResult(
        index: j['index'] as int,
        fqs: (j['fqs'] as num).toDouble(),
        tqs: ((j['tqs'] ?? 0) as num).toDouble(),
        sqs: ((j['sqs'] ?? 0) as num).toDouble(),
        role: j['role'] as String,
        passed: j['passed'] as bool,
        reason: (j['reason'] ?? '') as String,
        weakest: (j['weakest'] ?? '') as String,
      );

  /// What to fix first, in the seller's terms rather than the framework's.
  String? get improvement {
    if (passed) return null;
    switch (weakest) {
      case 'sharpness':
        return 'Not sharp enough. Keep the phone still and tap to focus.';
      case 'exposure':
        return 'Lighting is off. Try near a window, out of direct sun.';
      case 'background':
        return 'Background is not clean enough. Use a plain light surface.';
      case 'colorcast':
        return 'Colours look tinted. Change the lighting.';
      case 'brisque':
      case 'piqe':
        return 'Overall image quality is low. Clean the lens and retake.';
      case 'subject_centering':
        return 'Centre the product in the frame.';
      case 'feature_visibility':
        return 'Move closer so the details are clear.';
      case 'marketing_suitability':
        return 'Does not look ready to post. Improve lighting and framing.';
      case 'angle_value':
        return 'Try an angle that shows more of the product.';
      case 'lighting_style_quality':
        return 'Improve the lighting. Avoid harsh shadows.';
      default:
        if (reason.startsWith('t0')) {
          return 'This photo is too small for social media. Retake it with the app camera.';
        }
        if (reason.startsWith('semantic_failed')) {
          return 'The presentation check could not run. Check the connection and try again.';
        }
        if (reason == 'decode_failed') {
          return 'This file could not be opened as a photo. Choose another.';
        }
        return 'Retake this one.';
    }
  }

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

/// One uploaded photo as /batch explains it: chosen for the set or not, and why
/// (2026-10-06). One entry per photo, in upload order.
class BatchPhoto {
  final int index;
  final String role;
  final double fqs;
  final bool passed;
  final bool selected;

  /// selected | same_view | not_needed | not_good_enough
  final String status;

  /// A plain sentence for the owner, written by the server.
  final String message;

  /// The per-criterion scores the framework computed for this photo (T1..T6 and
  /// S1..S5), for DISPLAY only. Empty when the photo never reached that stage (a
  /// hard reject has no semantic scores).
  final Map<String, double> technical;
  final Map<String, double> semantic;

  BatchPhoto({
    required this.index,
    required this.role,
    required this.fqs,
    required this.passed,
    required this.selected,
    required this.status,
    required this.message,
    this.technical = const {},
    this.semantic = const {},
  });

  static Map<String, double> _scores(Object? v) => v is Map
      ? {
          for (final e in v.entries)
            if (e.value is num) e.key.toString(): (e.value as num).toDouble()
        }
      : const {};

  factory BatchPhoto.fromJson(Map<String, dynamic> j) => BatchPhoto(
        index: j['index'] as int,
        role: (j['role'] ?? '') as String,
        fqs: ((j['fqs'] ?? 0) as num).toDouble(),
        passed: (j['passed'] ?? false) as bool,
        selected: (j['selected'] ?? false) as bool,
        status: (j['status'] ?? '') as String,
        message: (j['message'] ?? '') as String,
        technical: _scores(j['technical']),
        semantic: _scores(j['semantic']),
      );

  /// Order of a set photo: main, angles, detail, then anything else.
  int get roleRank {
    switch (role) {
      case 'hero_shot':
        return 0;
      case 'angle_shot':
        return 1;
      case 'detail_shot':
        return 2;
      default:
        return 3;
    }
  }
}

/// One criterion as the server states it (GET /criteria): the pass threshold lives
/// on the server, never in the app, so the screen shows the standard in force.
class CriterionInfo {
  final String name;
  final double weight;
  final double? passThreshold;

  const CriterionInfo(this.name, this.weight, this.passThreshold);

  factory CriterionInfo.fromJson(Map<String, dynamic> j) => CriterionInfo(
        j['name'] as String,
        ((j['weight'] ?? 0) as num).toDouble(),
        (j['pass_threshold'] as num?)?.toDouble(),
      );
}

/// GET /criteria, read once, for the per-criterion breakdown (display only).
class CriteriaInfo {
  final List<CriterionInfo> technical;
  final List<CriterionInfo> semantic;
  final double? fqsPass;

  const CriteriaInfo(this.technical, this.semantic, this.fqsPass);

  factory CriteriaInfo.fromJson(Map<String, dynamic> j) {
    List<CriterionInfo> list(Object? v) => [
          for (final e in (v as List? ?? const []))
            CriterionInfo.fromJson(e as Map<String, dynamic>)
        ];
    final comb = j['combination'];
    return CriteriaInfo(
      list(j['technical']),
      list(j['semantic']),
      comb is Map ? (comb['pass_threshold'] as num?)?.toDouble() : null,
    );
  }
}

/// A shot still needed before the set can be certified.
class MissingShot {
  /// hero_shot | angle_shot | detail_shot
  final String role;
  final int count;
  final String message;

  MissingShot({required this.role, required this.count, required this.message});

  factory MissingShot.fromJson(Map<String, dynamic> j) => MissingShot(
        role: (j['role'] ?? '') as String,
        count: ((j['count'] ?? 1) as num).toInt(),
        message: (j['message'] ?? '') as String,
      );
}

/// Result of scoring a whole capture batch.
class BatchResult {
  final bool certified;
  final List<BatchImageResult> selected;
  final Map<String, List<String>> roleSets;
  final Map<String, dynamic>? recapture;

  /// Every photo, chosen or not, with the reason (2026-10-06).
  final List<BatchPhoto> images;

  /// Shots still needed; empty when certified.
  final List<MissingShot> missing;

  /// The model that answered, and the API tier (v1.4.0-rc). Logged with every
  /// study batch so a result can be traced to the build that produced it.
  final String modelVersion;
  final String tier;

  BatchResult({
    required this.certified,
    required this.selected,
    required this.roleSets,
    this.recapture,
    this.images = const [],
    this.missing = const [],
    this.modelVersion = '',
    this.tier = '',
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
      images: ((j['images'] as List?) ?? const [])
          .map((s) => BatchPhoto.fromJson(s as Map<String, dynamic>))
          .toList(),
      missing: ((j['missing'] as List?) ?? const [])
          .map((s) => MissingShot.fromJson(s as Map<String, dynamic>))
          .toList(),
      modelVersion: (j['model_version'] as String?) ?? '',
      tier: (j['tier'] as String?) ?? '',
    );
  }

  /// The chosen set, in role order (main, angles, detail).
  List<BatchPhoto> get setPhotos {
    final s = images.where((p) => p.selected).toList();
    s.sort((a, b) => a.roleRank != b.roleRank
        ? a.roleRank.compareTo(b.roleRank)
        : a.index.compareTo(b.index));
    return s;
  }

  /// Every photo not in the set, in upload order.
  List<BatchPhoto> get notUsed => images.where((p) => !p.selected).toList();

  /// What the user is told when the set is not good enough yet.
  String get recaptureInstruction =>
      recapture?['instruction'] as String? ?? 'Capture a few more images.';
}

/// One music track offered for a video. The server RECOMMENDS; the owner chooses.
class MusicTrack {
  final String id;
  final String title;
  final String mood;
  final bool recommended;
  final String attribution;

  MusicTrack({
    required this.id,
    required this.title,
    required this.mood,
    required this.recommended,
    required this.attribution,
  });

  factory MusicTrack.fromJson(Map<String, dynamic> j) => MusicTrack(
        id: j['id'] as String,
        title: (j['title'] ?? j['id']) as String,
        mood: (j['mood'] ?? '') as String,
        recommended: (j['recommended'] ?? false) as bool,
        attribution: (j['attribution'] ?? '') as String,
      );
}

/// The server's music recommendation plus the installed tracks.
class MusicRecommendation {
  final String recommendedMood;
  final String reason;
  final List<MusicTrack> tracks;
  final String note;

  /// mood -> one plain sentence describing it, from the server.
  final Map<String, String> moodDescriptions;

  MusicRecommendation({
    required this.recommendedMood,
    required this.reason,
    required this.tracks,
    required this.note,
    this.moodDescriptions = const {},
  });

  factory MusicRecommendation.fromJson(Map<String, dynamic> j) =>
      MusicRecommendation(
        recommendedMood: (j['recommended_mood'] ?? '') as String,
        reason: (j['reason'] ?? '') as String,
        tracks: (((j['tracks'] as List?) ?? const [])
            .map((t) => MusicTrack.fromJson(t as Map<String, dynamic>))
            .toList()),
        note: (j['note'] ?? '') as String,
        moodDescriptions: ((j['mood_descriptions'] as Map?) ?? const {})
            .map((k, v) => MapEntry(k.toString(), v.toString())),
      );

  /// The first installed track of [mood], or null if there is none.
  MusicTrack? firstTrack(String mood) {
    for (final t in tracks) {
      if (t.mood == mood) return t;
    }
    return null;
  }
}

/// One rule of the "ready to post" checklist in a video plan.
class ChecklistItem {
  final String rule;
  final bool met;
  final String detail;

  ChecklistItem({required this.rule, required this.met, required this.detail});

  factory ChecklistItem.fromJson(Map<String, dynamic> j) => ChecklistItem(
        rule: (j['rule'] ?? '') as String,
        met: (j['met'] ?? false) as bool,
        detail: (j['detail'] ?? '') as String,
      );
}

/// The plan returned by POST /video/plan. [raw] is kept whole for results.json.
class VideoPlan {
  final Map<String, dynamic> raw;

  VideoPlan(this.raw);

  String get planId => (raw['plan_id'] ?? '') as String;

  String get caption =>
      ((raw['post'] as Map?)?['caption'] ?? '') as String;

  num get durationSeconds => (raw['duration_seconds'] ?? 0) as num;

  List<ChecklistItem> get checklist => ((raw['checklist'] as List?) ?? const [])
      .map((c) => ChecklistItem.fromJson(c as Map<String, dynamic>))
      .toList();
}

/// The MP4 from POST /video/render, with what the server says about it.
class RenderedVideo {
  final Uint8List bytes;
  final String duration;
  final String format;
  final bool hasAudio;

  RenderedVideo({
    required this.bytes,
    required this.duration,
    required this.format,
    required this.hasAudio,
  });
}

/// A summary of the server from GET /health, for the About screen.
class HealthInfo {
  final String release;
  final String frameworkVersion;

  const HealthInfo({required this.release, required this.frameworkVersion});

  factory HealthInfo.fromJson(Map<String, dynamic> j) => HealthInfo(
        release: (j['release'] ?? '') as String,
        frameworkVersion: (j['framework_version'] ?? '') as String,
      );
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
    // Our own server's checks (v1.1.0): wrong access token, per-IP limit.
    if (status == 401 || lower.contains('bad_token')) {
      return ApiFailure.unauthorized(body);
    }
    if (status == 429 && lower.contains('rate_limited')) {
      return ApiFailure.rateLimited(body, serverDetail: _serverDetail(body));
    }
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
  Future<ApiResult<GuidanceResult>> guidance(
    Uint8List jpegBytes, {
    String shot = 'main',
    int rotation = 0,
  }) async {
    try {
      final req = http.MultipartRequest(
        'POST',
        Uri.parse('${ApiConfig.baseUrl}/guidance'),
      )
        ..headers.addAll(ApiConfig.authHeaders)
        // Per shot framing, and the rotation the server applies to upright a
        // sensor orientation frame before it checks the scored 4:5 region.
        ..fields['shot'] = shot
        ..fields['rotation'] = rotation.toString()
        ..files.add(http.MultipartFile.fromBytes(
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
      )..headers.addAll(ApiConfig.authHeaders);
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

  /// The URL that streams a track's audio preview, for the audio player.
  /// The audio player cannot send headers, so the token goes in the query.
  String musicPreviewUrl(String trackId) {
    final t = ApiConfig.apiToken;
    final q = t == null ? '' : '?token=${Uri.encodeQueryComponent(t)}';
    return '${ApiConfig.baseUrl}/music/preview/$trackId$q';
  }

  /// The criteria in force with their weights and pass thresholds (GET /criteria).
  /// Used only to DISPLAY the standard beside each score; nothing is decided here.
  Future<ApiResult<CriteriaInfo>> criteria() async {
    try {
      final r = await _client
          .get(Uri.parse('${ApiConfig.baseUrl}/criteria'),
              headers: ApiConfig.authHeaders)
          .timeout(const Duration(seconds: 15));
      if (r.statusCode != 200) {
        return ApiResult.failure(_fromResponse(r.statusCode, r.body));
      }
      return ApiResult.success(
          CriteriaInfo.fromJson(jsonDecode(r.body) as Map<String, dynamic>));
    } catch (e) {
      return ApiResult.failure(_classify(e));
    }
  }

  /// Recommends a music mood and lists the installed tracks for a category.
  Future<ApiResult<MusicRecommendation>> music(String? category) async {
    try {
      final uri = Uri.parse('${ApiConfig.baseUrl}/music').replace(
        queryParameters: (category != null && category.isNotEmpty)
            ? {'category': category}
            : null,
      );
      final r = await _client
          .get(uri, headers: ApiConfig.authHeaders)
          .timeout(const Duration(seconds: 15));
      if (r.statusCode != 200) {
        return ApiResult.failure(_fromResponse(r.statusCode, r.body));
      }
      return ApiResult.success(
          MusicRecommendation.fromJson(jsonDecode(r.body) as Map<String, dynamic>));
    } catch (e) {
      return ApiResult.failure(_classify(e));
    }
  }

  /// The `detail` FastAPI puts in an error body, or null.
  static String? _serverDetail(String body) {
    try {
      final d = (jsonDecode(body) as Map<String, dynamic>)['detail'];
      return d is String && d.isNotEmpty ? d : null;
    } catch (_) {
      return null;
    }
  }

  /// Classifies a failed /video/plan or /video/render response, logging the
  /// status and the start of the body so the real cause is visible.
  ApiFailure _videoFailure(String call, int status, String body) {
    final snippet = body.length > 300 ? body.substring(0, 300) : body;
    debugPrint('[video] $call failed: status=$status body=$snippet');
    final detail = _serverDetail(body);
    switch (status) {
      case 404: // plan expired, or its music track is gone
        return ApiFailure.videoPlanExpired(body, serverDetail: detail);
      case 503: // the server has no ffmpeg
        return ApiFailure.videoUnavailable(body);
      case 500: // the server tried and failed
        return ApiFailure.videoFailed(body, serverDetail: detail);
      case 502:
      case 504: // gateway timeout, usually a slow tunnel
        return ApiFailure.videoTimeout('HTTP $status. $body');
      default:
        return _fromResponse(status, body);
    }
  }

  ApiFailure _videoThrown(String call, Object e) {
    debugPrint('[video] $call threw: status=none body=$e');
    final text = e.toString();
    if (e is TimeoutException ||
        text.contains('TimeoutException') ||
        text.contains('timed out')) {
      return ApiFailure.videoTimeout(text);
    }
    return _classify(e);
  }

  /// Plans the marketing video from the certified set and the product form.
  ///
  /// The SAME original bytes that were scored are sent, never re-encoded. [roles]
  /// are in the same order as [images]. The server asks the model once where the
  /// features are, so this can take up to a minute.
  Future<ApiResult<VideoPlan>> videoPlan({
    required List<Uint8List> images,
    required List<String> roles,
    required ProductDraft draft,
  }) async {
    if (images.isEmpty) {
      return ApiResult.failure(ApiFailure.badImage('No images to send.'));
    }
    try {
      final req = http.MultipartRequest(
        'POST',
        Uri.parse('${ApiConfig.baseUrl}/video/plan'),
      )
        ..headers.addAll(ApiConfig.authHeaders)
        ..fields.addAll({
          'roles': roles.join(','),
          'product_name': draft.name,
          'price': draft.price,
          'features': draft.cleanFeatures.take(3).join('\n'),
          'category': draft.category,
          'mood': draft.mood,
          'format': draft.format,
          'shop': draft.shop,
          'contact': draft.contact,
          'brand_colour': draft.brandColour,
        });
      for (var i = 0; i < images.length; i++) {
        req.files.add(http.MultipartFile.fromBytes(
          'files',
          images[i],
          filename: 'image_$i.jpg',
          contentType: MediaType('image', 'jpeg'),
        ));
      }
      final streamed = await req.send().timeout(ApiConfig.videoPlanTimeout);
      final body = await streamed.stream
          .bytesToString()
          .timeout(ApiConfig.videoPlanTimeout);
      if (streamed.statusCode != 200) {
        return ApiResult.failure(
            _videoFailure('POST /video/plan', streamed.statusCode, body));
      }
      return ApiResult.success(
          VideoPlan(jsonDecode(body) as Map<String, dynamic>));
    } catch (e) {
      return ApiResult.failure(_videoThrown('POST /video/plan', e));
    }
  }

  /// The saved plan. After /video/render it holds the checklist MEASURED from
  /// the finished video (v1.1.0), which the result screen shows.
  Future<ApiResult<VideoPlan>> getVideoPlan(String planId) async {
    try {
      final r = await _client
          .get(Uri.parse('${ApiConfig.baseUrl}/video/plan/$planId'),
              headers: ApiConfig.authHeaders)
          .timeout(const Duration(seconds: 20));
      if (r.statusCode != 200) {
        return ApiResult.failure(
            _videoFailure('GET /video/plan', r.statusCode, r.body));
      }
      return ApiResult.success(
          VideoPlan(jsonDecode(r.body) as Map<String, dynamic>));
    } catch (e) {
      return ApiResult.failure(_videoThrown('GET /video/plan', e));
    }
  }

  /// Renders the MP4 from a saved plan. Up to three minutes.
  Future<ApiResult<RenderedVideo>> renderVideo(String planId) async {
    try {
      final req = http.MultipartRequest(
        'POST',
        Uri.parse('${ApiConfig.baseUrl}/video/render'),
      )
        ..headers.addAll(ApiConfig.authHeaders)
        ..fields['plan_id'] = planId;
      final streamed = await req.send().timeout(ApiConfig.videoTimeout);
      final bytes =
          await streamed.stream.toBytes().timeout(ApiConfig.videoTimeout);
      final status = streamed.statusCode;
      if (status != 200) {
        return ApiResult.failure(_videoFailure(
            'POST /video/render', status, utf8.decode(bytes, allowMalformed: true)));
      }
      final h = streamed.headers;
      return ApiResult.success(RenderedVideo(
        bytes: bytes,
        duration: h['x-video-duration'] ?? '',
        format: h['x-video-format'] ?? '',
        hasAudio: h['x-video-audio'] == '1',
      ));
    } catch (e) {
      return ApiResult.failure(_videoThrown('POST /video/render', e));
    }
  }

  /// The server's release and framework version (GET /health), for the About
  /// screen. Open endpoint, so no token is needed.
  Future<ApiResult<HealthInfo>> healthInfo() async {
    try {
      final r = await _client
          .get(Uri.parse('${ApiConfig.baseUrl}/health'))
          .timeout(const Duration(seconds: 8));
      if (r.statusCode != 200) {
        return ApiResult.failure(_fromResponse(r.statusCode, r.body));
      }
      return ApiResult.success(
          HealthInfo.fromJson(jsonDecode(r.body) as Map<String, dynamic>));
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
      // /health is open; this protected call shows a wrong token at once,
      // before the owner starts (v1.1.0).
      final a = await _client
          .get(Uri.parse('${ApiConfig.baseUrl}/auth/check'),
              headers: ApiConfig.authHeaders)
          .timeout(const Duration(seconds: 6));
      if (a.statusCode != 200 && a.statusCode != 404) {
        return ApiResult.failure(_fromResponse(a.statusCode, a.body));
      }
      return const ApiResult.success(true);
    } catch (e) {
      return ApiResult.failure(_classify(e));
    }
  }
}

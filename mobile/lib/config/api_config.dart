import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import '../models/study_session.dart';

/// Configuration for reaching the PQF API.
///
/// Settings come from a `.env` file that is not committed to the repository.
///
/// ROBUSTNESS NOTE. Every read goes through [_get], which tolerates dotenv not
/// being initialised at all. This matters because if the `.env` asset is
/// missing or malformed, `dotenv.load` fails, and any later call to
/// `dotenv.maybeGet` throws NotInitializedError from deep inside a widget
/// build, which surfaces as a crash rather than as a helpful message. A missing
/// configuration file should degrade to a clear connection error, not take the
/// app down.
///
/// A NOTE ON WHAT THIS DOES AND DOES NOT ACHIEVE. A value bundled into a mobile
/// application can be extracted from the installed package, so this is not a way
/// to hide a secret. What it gives you is configuration without editing source,
/// which matters because the server address changes whenever you change network,
/// and it keeps that address out of git history. The genuine secret, the model
/// API key, stays on the server and is never shipped to the client.
class ApiConfig {
  /// True once a `.env` has been loaded successfully. Set from main().
  static bool loaded = false;

  /// Reads a key, returning null rather than throwing if dotenv is unavailable.
  static String? _get(String key) {
    if (!loaded) return null;
    try {
      if (!dotenv.isInitialized) return null;
      final v = dotenv.maybeGet(key);
      if (v == null || v.trim().isEmpty) return null;
      return v.trim();
    } catch (_) {
      return null;
    }
  }

  static int _int(String key, int fallback, int min, int max) {
    final parsed = int.tryParse(_get(key) ?? '');
    if (parsed == null) return fallback;
    return parsed.clamp(min, max);
  }

  /// Where the API is running. Trailing slashes are stripped so joining paths
  /// never produces a double slash. A value with no scheme automatically gets https:// added, because without a scheme Uri.parse
  /// reads the whole string as a path with an empty host and every request fails.
  static String get baseUrl {
    final v = _get('PQF_API_BASE_URL');
    if (v == null) {
      debugPrint(
        'PQF_API_BASE_URL not available. Check that assets/config.env exists, '
        'that it is listed under assets in pubspec.yaml, and that you ran '
        'flutter clean after adding it. Falling '
        'back to the Android emulator host alias, which a physical phone '
        'cannot reach.',
      );
      return 'http://10.0.2.2:8000';
    }
    final withScheme = v.contains('://') ? v : 'https://$v';
    return withScheme.replaceAll(RegExp(r'/+$'), '');
  }

  /// How often a live guidance frame is sent. Raise if the preview stutters.
  /// The floor is 500 ms so frames are never sent faster than that (combined
  /// with the single in-flight guard, this bounds the camera's memory churn).
  static Duration get guidanceInterval =>
      Duration(milliseconds: _int('PQF_GUIDANCE_INTERVAL_MS', 700, 500, 3000));

  /// Abandon a guidance frame after this long. A dropped frame is harmless.
  static Duration get guidanceTimeout =>
      Duration(milliseconds: _int('PQF_GUIDANCE_TIMEOUT_MS', 4000, 1000, 15000));

  /// Batch scoring calls the semantic model once per image, so allow plenty.
  static Duration get batchTimeout =>
      Duration(milliseconds: _int('PQF_BATCH_TIMEOUT_MS', 180000, 30000, 600000));

  /// Video assembly runs ffmpeg on the server, which takes several seconds per
  /// image. At least 120 seconds, so a larger set does not time out.
  static Duration get videoTimeout =>
      Duration(milliseconds: _int('PQF_VIDEO_TIMEOUT_MS', 180000, 120000, 600000));

  /// POST /video/plan uploads the set and asks the model once where the
  /// features are, so allow up to a minute.
  static Duration get videoPlanTimeout =>
      Duration(milliseconds: _int('PQF_VIDEO_PLAN_TIMEOUT_MS', 60000, 30000, 300000));

  /// The 4 digit PIN that opens study mode (PQF_STUDY_PIN). Null, or anything
  /// that is not 4 digits, means study mode cannot be opened.
  static String? get studyPin {
    final v = _get('PQF_STUDY_PIN');
    return (v != null && RegExp(r'^\d{4}$').hasMatch(v)) ? v : null;
  }

  /// Shared token for a deployed server (PQF_API_TOKEN), sent as X-PQF-Token.
  /// The server only checks it when its own PQF_API_TOKEN is set.
  static String? get apiToken => _get('PQF_API_TOKEN');

  /// Headers every request carries.
  ///
  /// While a study session is running the requests also carry X-PQF-Study: 1, so
  /// the server does not apply its per-IP limits to them (all participants share
  /// one Wi-Fi). The server honours it only together with a valid token.
  static Map<String, String> get authHeaders {
    final t = apiToken;
    return {
      if (t != null) 'X-PQF-Token': t,
      if (StudySession.current != null) 'X-PQF-Study': '1',
    };
  }

  /// Shown on the home screen so the configured target is visible at a glance.
  static String get displayTarget {
    final u = Uri.tryParse(baseUrl);
    final where =
        u == null ? baseUrl : '${u.host}${u.hasPort ? ':${u.port}' : ''}';
    return loaded ? where : '$where  (no config loaded)';
  }
}

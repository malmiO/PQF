/// Result of an API call, either a value or a failure the user can act on.
///
/// The app never shows a raw exception. Every failure is classified into a
/// cause, given a message written for a seller rather than a developer, and
/// where possible given a suggested action. A message like
/// "SocketException: Connection refused" tells the user nothing they can do.
class ApiResult<T> {
  final T? value;
  final ApiFailure? failure;

  const ApiResult.success(this.value) : failure = null;
  const ApiResult.failure(this.failure) : value = null;

  bool get ok => failure == null;
}

enum FailureKind {
  /// The server could not be reached at all.
  unreachable,

  /// The server was reached but took too long to answer.
  timeout,

  /// The daily or per minute allowance for the semantic model is exhausted.
  quotaExceeded,

  /// The server answered with an error.
  serverError,

  /// The image could not be read or was rejected.
  badImage,

  /// The server refused the app's access token (v1.1.0).
  unauthorized,

  /// Too many requests from this network in the last hour (v1.1.0).
  rateLimited,

  /// Anything not otherwise classified.
  unknown,
}

class ApiFailure {
  final FailureKind kind;

  /// What the user is told. Plain language, no technical terms.
  final String message;

  /// What they can do about it, if there is something.
  final String? action;

  /// The underlying detail, for the debug console only. Never shown.
  final String? technical;

  const ApiFailure({
    required this.kind,
    required this.message,
    this.action,
    this.technical,
  });

  /// Whether offering a (user-tapped) retry button makes sense. This never
  /// auto-resubmits; it only enables a manual "Try again". Busy/quota (429) are
  /// included so the user can retry after waiting a minute (B5, 2026-10-13).
  bool get retryable =>
      kind == FailureKind.unreachable ||
      kind == FailureKind.timeout ||
      kind == FailureKind.serverError ||
      kind == FailureKind.rateLimited ||
      kind == FailureKind.quotaExceeded;

  static ApiFailure unreachable(String? detail) => ApiFailure(
        kind: FailureKind.unreachable,
        message: 'Cannot reach the photo checking service.',
        action: 'Check that the server is running, and that this phone and the '
            'computer are on the same network.',
        technical: detail,
      );

  static ApiFailure timeout(String? detail) => ApiFailure(
        kind: FailureKind.timeout,
        message: 'Server is taking longer than usual. Please wait and try again.',
        action: 'Your photos are safe. Wait a moment, then try again.',
        technical: detail,
      );

  static ApiFailure quota(String? detail) => ApiFailure(
        kind: FailureKind.quotaExceeded,
        message: 'AI service is busy. Wait a minute and retry.',
        action: 'Your photos are safe. Try again shortly.',
        technical: detail,
      );

  static ApiFailure server(int status, String? detail) => ApiFailure(
        kind: FailureKind.serverError,
        message: 'Server error, please retry.',
        action: 'Try again. If it keeps happening, tell the person who set it up.',
        technical: 'HTTP $status. $detail',
      );

  static ApiFailure unauthorized(String? detail) => ApiFailure(
        kind: FailureKind.unauthorized,
        message: 'This app is not allowed to use the photo checking service.',
        action: 'The access token in the app settings (PQF_API_TOKEN in '
            'config.env) does not match the server. Ask the person who set it up.',
        technical: detail,
      );

  static ApiFailure rateLimited(String? detail, {String? serverDetail}) => ApiFailure(
        kind: FailureKind.rateLimited,
        message: 'AI service is busy. Wait a minute and retry.',
        action: serverDetail ?? 'Try again in a minute. Your photos are safe.',
        technical: detail,
      );

  static ApiFailure badImage(String? detail) => ApiFailure(
        kind: FailureKind.badImage,
        message: 'That photo could not be read.',
        action: 'Take it again.',
        technical: detail,
      );

  static ApiFailure unknown(String? detail) => ApiFailure(
        kind: FailureKind.unknown,
        message: 'Something went wrong while checking your photos.',
        action: 'Try again.',
        technical: detail,
      );

  /// The saved video plan, or its music, is gone from the server (404 from
  /// /video/render). Trying again plans the video afresh.
  static ApiFailure videoPlanExpired(String? detail, {String? serverDetail}) =>
      ApiFailure(
        kind: FailureKind.serverError,
        message: serverDetail ?? 'The video plan has expired.',
        action: planExpiredAction,
        technical: detail,
      );

  static const String planExpiredAction =
      'Try again to plan and make the video afresh.';

  /// True for [videoPlanExpired]: the plan must be made again before rendering.
  bool get planExpired => action == planExpiredAction;

  /// Video making is unavailable because the server has no ffmpeg (503).
  static ApiFailure videoUnavailable(String? detail) => ApiFailure(
        kind: FailureKind.serverError,
        message: 'Video making is not available on the server right now.',
        action: 'Your photos are saved. You can still save and share them.',
        technical: detail,
      );

  /// The server tried to make the video but failed (500). Distinct from 503 so
  /// a genuine assembly error is not hidden behind "not available".
  /// [serverDetail] is the server's own explanation, shown to the owner.
  static ApiFailure videoFailed(String? detail, {String? serverDetail}) =>
      ApiFailure(
        kind: FailureKind.serverError,
        message: 'The video could not be made. Try again.',
        action: serverDetail == null || serverDetail.isEmpty
            ? 'If it keeps happening, try with fewer images.'
            : 'The server said: $serverDetail',
        technical: detail,
      );

  /// A gateway timeout (502/504) or a client-side timeout while making the
  /// video. The server (AI + rendering) is slow; it is NOT the phone's
  /// connection, so the wording never blames the signal (B1, 2026-10-13).
  static ApiFailure videoTimeout(String? detail) => ApiFailure(
        kind: FailureKind.timeout,
        message: 'The video is taking longer than usual. Please wait and try again.',
        action: 'Your photos are safe. Wait a moment, then try again.',
        technical: detail,
      );
}

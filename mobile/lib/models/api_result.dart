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

  /// Whether offering a retry button makes sense. Retrying a quota failure
  /// immediately just fails again, so it is not offered.
  bool get retryable =>
      kind == FailureKind.unreachable ||
      kind == FailureKind.timeout ||
      kind == FailureKind.serverError;

  static ApiFailure unreachable(String? detail) => ApiFailure(
        kind: FailureKind.unreachable,
        message: 'Cannot reach the photo checking service.',
        action: 'Check that the server is running, and that this phone and the '
            'computer are on the same network.',
        technical: detail,
      );

  static ApiFailure timeout(String? detail) => ApiFailure(
        kind: FailureKind.timeout,
        message: 'The service is taking longer than expected.',
        action: 'This usually clears on its own. Try again in a moment.',
        technical: detail,
      );

  static ApiFailure quota(String? detail) => ApiFailure(
        kind: FailureKind.quotaExceeded,
        message: 'The daily limit for photo checking has been reached.',
        action: 'Your photos are safe. Checking will work again tomorrow.',
        technical: detail,
      );

  static ApiFailure server(int status, String? detail) => ApiFailure(
        kind: FailureKind.serverError,
        message: 'The photo checking service reported a problem.',
        action: 'Try again. If it keeps happening, restart the server.',
        technical: 'HTTP $status. $detail',
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
  /// video, usually a slow tunnel or connection rather than a server fault.
  static ApiFailure videoTimeout(String? detail) => ApiFailure(
        kind: FailureKind.timeout,
        message: 'The connection timed out while making the video. '
            'Try again on a stronger connection.',
        action: 'Use Wi-Fi or a stronger signal, then try again.',
        technical: detail,
      );
}

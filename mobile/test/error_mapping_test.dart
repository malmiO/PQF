import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/api_result.dart';

/// B1 (2026-10-13): honest error wording. Timeouts/5xx/429 must not be shown as
/// a connection/signal problem; only a real SocketException/DNS failure is
/// "cannot reach". Busy/quota are user-retryable.
void main() {
  test('timeout: "taking longer", never signal, retryable', () {
    final f = ApiFailure.timeout('TimeoutException');
    expect(f.message.toLowerCase(), contains('taking longer'));
    expect(f.message.toLowerCase(), isNot(contains('signal')));
    expect(f.message.toLowerCase(), isNot(contains('connection')));
    expect(f.retryable, isTrue);
  });

  test('quota / 429: "busy", retryable', () {
    final f = ApiFailure.quota('RESOURCE_EXHAUSTED');
    expect(f.message.toLowerCase(), contains('busy'));
    expect(f.retryable, isTrue);
  });

  test('rate limited: "busy", retryable', () {
    final f = ApiFailure.rateLimited('rate_limited');
    expect(f.message.toLowerCase(), contains('busy'));
    expect(f.retryable, isTrue);
  });

  test('5xx: "server error", retryable', () {
    final f = ApiFailure.server(500, 'boom');
    expect(f.message.toLowerCase(), contains('server error'));
    expect(f.retryable, isTrue);
  });

  test('video timeout: never "stronger connection" or "signal"', () {
    final m = ApiFailure.videoTimeout('504').message.toLowerCase();
    expect(m, isNot(contains('stronger connection')));
    expect(m, isNot(contains('signal')));
    expect(m, contains('taking longer'));
  });

  test('unreachable is the only connectivity-flavoured failure', () {
    final f = ApiFailure.unreachable('SocketException');
    expect(f.kind, FailureKind.unreachable);
    expect(f.retryable, isTrue);
  });

  test('badImage stays non-retryable (retry would fail again)', () {
    expect(ApiFailure.badImage('x').retryable, isFalse);
  });
}

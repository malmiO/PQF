import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/config/api_config.dart';
import 'package:mobile/models/study_session.dart';

// v1.4.0-rc: study requests carry X-PQF-Study: 1 so the server skips its per-IP
// limits (all participants share one Wi-Fi). Outside a study the header is absent.
void main() {
  tearDown(() => StudySession.current = null);

  test('no study session: no X-PQF-Study header', () {
    StudySession.current = null;
    expect(ApiConfig.authHeaders.containsKey('X-PQF-Study'), isFalse);
  });

  test('during a study session: X-PQF-Study is 1', () {
    StudySession.current =
        StudySession(participant: 'P01', product: 'K1', session: 1);
    expect(ApiConfig.authHeaders['X-PQF-Study'], '1');
  });

  test('header disappears when the session ends', () {
    StudySession.current =
        StudySession(participant: 'P01', product: 'K1', session: 1);
    StudySession.current = null;
    expect(ApiConfig.authHeaders.containsKey('X-PQF-Study'), isFalse);
  });
}

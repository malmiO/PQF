import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/auto_zoom.dart';

void main() {
  double? next(double current, double hint, {double max = 3.0}) =>
      AutoZoom.next(current: current, hint: hint, min: 1.0, max: max);

  test('a small product zooms in most of the way at once', () {
    final z = next(1.0, 1.8)!;
    expect(z, greaterThan(1.5));
    expect(z, lessThan(1.8)); // damped: no overshoot
  });

  test('auto zoom never goes above 2x, even when the hint asks for more', () {
    expect(next(1.0, 2.0)!, lessThanOrEqualTo(AutoZoom.autoCap));
    expect(next(1.9, 2.0)!, AutoZoom.autoCap);
    expect(next(2.0, 2.0), isNull); // already at the cap: leave it
  });

  test('a zoom the owner set above 2x is not pulled back by a zoom-in hint', () {
    expect(next(2.6, 1.5), isNull);
  });

  test('zooming out stops at the widest view', () {
    expect(next(1.5, 0.85)!, lessThan(1.5));
    expect(next(1.0, 0.85), isNull); // cannot go wider than 1x
  });

  test('hints inside the dead band and tiny changes are ignored', () {
    expect(next(1.4, 1.05), isNull);
    expect(next(1.4, 0.95), isNull);
  });

  test('a phone with a lower maximum zoom is respected', () {
    expect(next(1.0, 2.0, max: 1.6)!, 1.6);
  });

  test('auto zoom is limited by the camera resolution', () {
    expect(AutoZoom.capFor(1080), closeTo(1.2, 1e-9)); // J6+: 1080p photos
    expect(AutoZoom.capFor(2160), AutoZoom.autoCap); // 4K camera: 2x
    expect(AutoZoom.capFor(720), 1.0); // never below the widest view
    final z = AutoZoom.next(
        current: 1.0, hint: 2.0, min: 1.0, max: 3.0, cap: AutoZoom.capFor(1080))!;
    expect(z, closeTo(1.2, 1e-9));
  });
}

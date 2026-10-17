import 'dart:math' as math;

/// Auto zoom (v1.1.0): turns the server's zoom hint into the next zoom level.
///
/// The hint is the factor, relative to the CURRENT zoom, that would bring the
/// product to its target size. The camera moves most of the way at once
/// ([damping]) so it settles in one or two steps without overshooting, never
/// above [autoCap] (digital zoom softens the photo; the manual slider still
/// goes to 3x), and never below the camera's widest view.
class AutoZoom {
  /// Highest zoom auto zoom will ever choose. The owner can go further by hand.
  static const double autoCap = 2.0;

  /// Width of the photo the framework scores (the 4:5 crop of a 1080p photo).
  static const double outputWidth = 1080;

  /// Digital zoom enlarges a crop of the photo. Beyond the zoom at which the
  /// crop is narrower than [outputWidth] the photo is mostly enlarged pixels and
  /// comes out soft (J6+, 2026-10-06: 2x on its 1080p camera scored sharpness
  /// 0.45 to 0.53 against 0.66 to 0.80 unzoomed). This allows a mild 20 percent
  /// enlargement at most. [captureShortSide] is the photo's short side in
  /// pixels: 1080 on the J6+ (cap 1.2x), 2160 on a 4K camera (cap 2x).
  static double capFor(double captureShortSide) =>
      (captureShortSide / outputWidth * 1.2).clamp(1.0, autoCap).toDouble();

  /// Share of the hinted change applied at once (in log terms).
  static const double damping = 0.8;

  /// Hints closer to 1.0 than this are ignored (dead band).
  static const double deadBand = 0.08;

  /// At most one automatic change in this time, so the zoom does not hunt.
  static const Duration minInterval = Duration(milliseconds: 1000);

  /// Frames sent sooner than this after a zoom change still show the old zoom;
  /// they are not used for another change or for auto-capture.
  static const Duration settle = Duration(milliseconds: 400);

  /// The next zoom level, or null to leave the zoom as it is.
  static double? next({
    required double current,
    required double hint,
    required double min,
    required double max,
    double cap = autoCap,
  }) {
    if ((hint - 1.0).abs() < deadBand) return null;
    final wanted = current * math.pow(hint, damping);
    // Zooming in stops at autoCap, but never pulls back a zoom the owner chose.
    final upper = hint > 1.0 ? math.max(current, math.min(cap, max)) : max;
    final target = wanted.clamp(min, upper).toDouble();
    return (target - current).abs() < 0.05 ? null : target;
  }
}

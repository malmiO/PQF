import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;

/// Converts a camera stream frame into JPEG bytes for the guidance endpoint.
///
/// PERFORMANCE NOTE, and the most likely thing to need tuning on your device.
/// The camera delivers frames in a platform specific format, YUV420 on Android
/// and BGRA8888 on iOS, and converting them in Dart is not free. The conversion
/// is therefore done at a reduced size and only on throttled frames, never on
/// every frame. If guidance feels sluggish on your handset, reduce
/// `targetWidth` before changing anything else.
///
/// This runs on a background isolate via `compute` in the capture screen, so it
/// does not block the camera preview.
class FrameConverter {
  /// Width the frame is reduced to before encoding. The API reduces further,
  /// so there is no benefit in sending anything large.
  static const int targetWidth = 480;

  /// JPEG quality for guidance frames. Low is fine, since the guidance criteria
  /// are tolerant and the frame is discarded immediately.
  static const int jpegQuality = 70;

  /// Entry point for `compute`. Takes a simplified payload because isolates
  /// cannot receive a CameraImage directly.
  static Uint8List convert(FramePayload p) {
    final image = p.isYuv ? _fromYuv420(p) : _fromBgra(p);
    final resized = img.copyResize(
      image,
      width: targetWidth,
      interpolation: img.Interpolation.average,
    );
    return Uint8List.fromList(img.encodeJpg(resized, quality: jpegQuality));
  }

  static img.Image _fromYuv420(FramePayload p) {
    final out = img.Image(width: p.width, height: p.height);
    final uvRowStride = p.uvRowStride!;
    final uvPixelStride = p.uvPixelStride!;

    for (var y = 0; y < p.height; y++) {
      for (var x = 0; x < p.width; x++) {
        final uvIndex =
            uvPixelStride * (x >> 1) + uvRowStride * (y >> 1);
        final yIndex = y * p.yRowStride! + x;

        final yv = p.planeY[yIndex];
        final uv = p.planeU![uvIndex];
        final vv = p.planeV![uvIndex];

        // Standard YUV to RGB conversion.
        var r = (yv + 1.402 * (vv - 128)).round();
        var g = (yv - 0.344136 * (uv - 128) - 0.714136 * (vv - 128)).round();
        var b = (yv + 1.772 * (uv - 128)).round();

        out.setPixelRgb(
          x,
          y,
          r.clamp(0, 255),
          g.clamp(0, 255),
          b.clamp(0, 255),
        );
      }
    }
    return out;
  }

  static img.Image _fromBgra(FramePayload p) {
    return img.Image.fromBytes(
      width: p.width,
      height: p.height,
      bytes: p.planeY.buffer,
      order: img.ChannelOrder.bgra,
    );
  }
}

/// Isolate safe payload extracted from a CameraImage.
class FramePayload {
  final int width;
  final int height;
  final bool isYuv;
  final Uint8List planeY;
  final Uint8List? planeU;
  final Uint8List? planeV;
  final int? yRowStride;
  final int? uvRowStride;
  final int? uvPixelStride;

  FramePayload({
    required this.width,
    required this.height,
    required this.isYuv,
    required this.planeY,
    this.planeU,
    this.planeV,
    this.yRowStride,
    this.uvRowStride,
    this.uvPixelStride,
  });

  factory FramePayload.fromCameraImage(CameraImage image) {
    final isYuv = image.format.group == ImageFormatGroup.yuv420;
    return FramePayload(
      width: image.width,
      height: image.height,
      isYuv: isYuv,
      planeY: image.planes[0].bytes,
      planeU: isYuv ? image.planes[1].bytes : null,
      planeV: isYuv ? image.planes[2].bytes : null,
      yRowStride: isYuv ? image.planes[0].bytesPerRow : null,
      uvRowStride: isYuv ? image.planes[1].bytesPerRow : null,
      uvPixelStride: isYuv ? image.planes[1].bytesPerPixel : null,
    );
  }
}

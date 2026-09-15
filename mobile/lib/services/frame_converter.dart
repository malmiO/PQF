import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;

/// Converts a camera frame into JPEG bytes for the guidance endpoint.
///
/// PERFORMANCE, AND WHY THIS IS WRITTEN THE WAY IT IS.
///
/// The obvious implementation converts every source pixel and then resizes.
/// On a 1280 by 720 preview that is 921,600 pixels, each needing several
/// floating point operations, in pure Dart. It takes seconds per frame, the
/// guidance request never returns, and the camera appears to hang. That is
/// exactly what happened in the first version of this file.
///
/// This version samples DIRECTLY at the target size. For a 320 pixel wide
/// target from a 1280 by 720 source that is 57,600 pixels rather than 921,600,
/// which is sixteen times less work. Nearest neighbour sampling is perfectly
/// adequate here, because the result is fed to coarse quality checks and then
/// discarded, never shown to anyone.
class FrameConverter {
  /// Target width for the guidance frame. The server reduces further, so there
  /// is nothing to gain from sending anything larger. Lower this first if the
  /// preview stutters.
  static const int targetWidth = 320;

  /// JPEG quality. Low is fine for a frame that is measured and thrown away.
  static const int jpegQuality = 65;

  static Uint8List convert(FramePayload p) {
    final image = p.isYuv ? _sampleYuv420(p) : _sampleBgra(p);
    return Uint8List.fromList(img.encodeJpg(image, quality: jpegQuality));
  }

  /// Samples a YUV420 frame straight into an RGB image at the target size.
  static img.Image _sampleYuv420(FramePayload p) {
    final tw = p.width < targetWidth ? p.width : targetWidth;
    final th = (p.height * tw / p.width).round().clamp(1, p.height);

    final out = img.Image(width: tw, height: th);
    final yRow = p.yRowStride!;
    final uvRow = p.uvRowStride!;
    final uvPix = p.uvPixelStride!;
    final yPlane = p.planeY;
    final uPlane = p.planeU!;
    final vPlane = p.planeV!;
    final yLen = yPlane.length;
    final uLen = uPlane.length;
    final vLen = vPlane.length;

    for (var ty = 0; ty < th; ty++) {
      final sy = ty * p.height ~/ th;
      final yBase = sy * yRow;
      final uvBase = (sy >> 1) * uvRow;

      for (var tx = 0; tx < tw; tx++) {
        final sx = tx * p.width ~/ tw;

        final yIdx = yBase + sx;
        final uvIdx = uvBase + (sx >> 1) * uvPix;

        // Guard rather than assume. Stride and plane sizes vary by device, and
        // a single out of range read would crash the isolate mid frame.
        if (yIdx >= yLen || uvIdx >= uLen || uvIdx >= vLen) continue;

        final yv = yPlane[yIdx];
        final uv = uPlane[uvIdx] - 128;
        final vv = vPlane[uvIdx] - 128;

        var r = (yv + 1.402 * vv).round();
        var g = (yv - 0.344136 * uv - 0.714136 * vv).round();
        var b = (yv + 1.772 * uv).round();

        if (r < 0) r = 0; else if (r > 255) r = 255;
        if (g < 0) g = 0; else if (g > 255) g = 255;
        if (b < 0) b = 0; else if (b > 255) b = 255;

        out.setPixelRgb(tx, ty, r, g, b);
      }
    }
    return out;
  }

  /// Samples a BGRA frame, which is what iOS delivers.
  static img.Image _sampleBgra(FramePayload p) {
    final tw = p.width < targetWidth ? p.width : targetWidth;
    final th = (p.height * tw / p.width).round().clamp(1, p.height);

    final out = img.Image(width: tw, height: th);
    final bytes = p.planeY;
    final rowStride = p.yRowStride ?? (p.width * 4);
    final len = bytes.length;

    for (var ty = 0; ty < th; ty++) {
      final sy = ty * p.height ~/ th;
      final base = sy * rowStride;
      for (var tx = 0; tx < tw; tx++) {
        final sx = tx * p.width ~/ tw;
        final i = base + sx * 4;
        if (i + 2 >= len) continue;
        out.setPixelRgb(tx, ty, bytes[i + 2], bytes[i + 1], bytes[i]);
      }
    }
    return out;
  }
}

/// Isolate safe payload extracted from a CameraImage.
///
/// A CameraImage cannot cross an isolate boundary, so the plane bytes and the
/// stride values are copied out first.
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
    final isYuv = image.format.group == ImageFormatGroup.yuv420 &&
        image.planes.length >= 3;
    return FramePayload(
      width: image.width,
      height: image.height,
      isYuv: isYuv,
      planeY: image.planes[0].bytes,
      planeU: isYuv ? image.planes[1].bytes : null,
      planeV: isYuv ? image.planes[2].bytes : null,
      yRowStride: image.planes[0].bytesPerRow,
      uvRowStride: isYuv ? image.planes[1].bytesPerRow : null,
      uvPixelStride: isYuv ? (image.planes[1].bytesPerPixel ?? 1) : null,
    );
  }
}

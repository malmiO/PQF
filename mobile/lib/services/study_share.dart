import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:share_plus/share_plus.dart';

/// Sends an exported study zip with the Android share sheet (2026-10-15), so a
/// participant can pass it on from their own phone (WhatsApp, Gmail, Drive, ...).
///
/// HOW THE FILE REACHES THE OTHER APP. share_plus copies the file into
/// `<cache>/share_plus/` and hands out a `content://` URI from its own FileProvider
/// (authority `<applicationId>.flutter.share_provider`, exported=false,
/// grantUriPermissions=true, paths = cache-path share_plus/), with a read grant. A
/// `file://` path is never sent (it throws FileUriExposedException on API 24+). The zip
/// itself stays where the export wrote it, in the app's external folder, for adb.
class StudyShare {
  /// The MIME type the receiving app is told about.
  static const mimeType = 'application/zip';

  /// For tests only: replaces the real share sheet.
  @visibleForTesting
  static SharePlus? sharer;

  /// What is handed to the share sheet for [zip]: one file, typed application/zip.
  static ShareParams paramsFor(File zip) {
    final name = zip.uri.pathSegments.isEmpty ? 'study.zip' : zip.uri.pathSegments.last;
    return ShareParams(
      files: [XFile(zip.path, mimeType: mimeType)],
      subject: 'PQF study data: $name',
      title: 'Send the study data',
    );
  }

  /// Opens the share sheet for [zip]. Throws if the platform cannot.
  static Future<ShareResult> share(File zip) =>
      (sharer ?? SharePlus.instance).share(paramsFor(zip));
}

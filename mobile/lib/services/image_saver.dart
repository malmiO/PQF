import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:gal/gal.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../services/pqf_api.dart';

/// Saves the certified image set to the phone.
///
/// WHY THIS OUTPUT EXISTS. Expert consultation established that sellers
/// repeatedly need to send individual images to customers during a conversation,
/// and re-shoot because they have nothing ready. A set that lives only inside
/// the app does not solve that. The images must end up somewhere the seller can
/// reach from WhatsApp or Instagram.
///
/// WHY FILES ARE NAMED BY ROLE. The role is what makes the set useful. A seller
/// scrolling their gallery can tell the main shot from a detail shot without
/// opening anything, which is the difference between a usable set and four
/// similar looking files.
///
/// WHY ONLY ACCEPTED IMAGES ARE SAVED. Saving rejected images alongside accepted
/// ones would undermine the point of certifying them. The user is told plainly
/// how many were saved and how many were left out.
class ImageSaver {
  /// Outcome of an attempt to save.
  static const String methodGallery = 'gallery';
  static const String methodShare = 'share';

  /// Saves the accepted images, named by product and role.
  ///
  /// Tries the gallery first. If that is refused or unavailable, falls back to
  /// writing temporary files and opening the system share sheet, which needs no
  /// permission and still lets the seller send the images to a customer.
  static Future<SaveOutcome> save({
    required String productName,
    required BatchResult result,
    required List<Uint8List> images,
  }) async {
    final items = <_NamedImage>[];
    final counts = <String, int>{};

    for (final selected in result.selected) {
      if (!selected.passed) continue;
      if (selected.index < 0 || selected.index >= images.length) continue;

      final role = _roleSlug(selected.role);
      counts[role] = (counts[role] ?? 0) + 1;
      final suffix = counts[role]! > 1 ? '_${counts[role]}' : '';
      items.add(_NamedImage(
        name: '${_slug(productName)}_$role$suffix.jpg',
        bytes: images[selected.index],
      ));
    }

    if (items.isEmpty) {
      return SaveOutcome(
        saved: 0,
        excluded: images.length,
        method: methodGallery,
        error: 'None of these photos passed the quality check yet.',
      );
    }

    final excluded = images.length - items.length;

    // Preferred path, the gallery.
    try {
      final hasAccess = await Gal.hasAccess(toAlbum: true);
      if (!hasAccess) {
        final granted = await Gal.requestAccess(toAlbum: true);
        if (!granted) {
          return _shareFallback(items, excluded,
              reason: 'Permission to save to your photos was not granted.');
        }
      }

      final album = _slug(productName);
      final dir = await getTemporaryDirectory();
      for (final item in items) {
        final f = File('${dir.path}/${item.name}');
        await f.writeAsBytes(item.bytes, flush: true);
        await Gal.putImage(f.path, album: album);
      }

      return SaveOutcome(
        saved: items.length,
        excluded: excluded,
        method: methodGallery,
        albumName: album,
      );
    } catch (e) {
      debugPrint('Gallery save failed, falling back to share. $e');
      return _shareFallback(items, excluded,
          reason: 'Saving to your photos did not work on this phone.');
    }
  }

  /// Writes the images to temporary files and opens the share sheet.
  ///
  /// This needs no storage permission at all, which is why it is the fallback.
  /// The seller can send the set straight to a customer, or save it from the
  /// share sheet if they prefer.
  static Future<SaveOutcome> _shareFallback(
    List<_NamedImage> items,
    int excluded, {
    required String reason,
  }) async {
    try {
      final dir = await getTemporaryDirectory();
      final files = <XFile>[];
      for (final item in items) {
        final f = File('${dir.path}/${item.name}');
        await f.writeAsBytes(item.bytes, flush: true);
        files.add(XFile(f.path));
      }
      await Share.shareXFiles(files, subject: 'Product photos');
      return SaveOutcome(
        saved: items.length,
        excluded: excluded,
        method: methodShare,
        note: reason,
      );
    } catch (e) {
      return SaveOutcome(
        saved: 0,
        excluded: excluded,
        method: methodShare,
        error: 'Could not save or share the photos. $e',
      );
    }
  }

  /// Role names the seller understands, used in the filename.
  static String _roleSlug(String role) {
    switch (role) {
      case 'hero_shot':
        return 'main';
      case 'angle_shot':
        return 'angle';
      case 'detail_shot':
        return 'detail';
      default:
        return 'extra';
    }
  }

  /// Filename safe version of the product name.
  static String _slug(String s) {
    final cleaned = s
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
        .replaceAll(RegExp(r'^_+|_+$'), '');
    return cleaned.isEmpty ? 'product' : cleaned;
  }
}

class _NamedImage {
  final String name;
  final Uint8List bytes;

  _NamedImage({required this.name, required this.bytes});
}

class SaveOutcome {
  final int saved;
  final int excluded;
  final String method;
  final String? albumName;
  final String? note;
  final String? error;

  SaveOutcome({
    required this.saved,
    required this.excluded,
    required this.method,
    this.albumName,
    this.note,
    this.error,
  });

  bool get ok => saved > 0 && error == null;

  /// What the user is told afterwards, in their terms rather than the app's.
  String get message {
    if (error != null) return error!;
    final where = method == ImageSaver.methodGallery
        ? (albumName == null
            ? 'in your photos'
            : 'in your photos, in an album called $albumName')
        : 'ready to send';
    final base = saved == 1
        ? 'One photo is $where.'
        : '$saved photos are $where.';
    if (excluded > 0) {
      return '$base ${excluded == 1 ? "One photo was" : "$excluded photos were"} '
          'left out because they did not meet the standard.';
    }
    return base;
  }
}

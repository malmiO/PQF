import 'dart:typed_data';

/// What the owner told us about the product, on the first screen of a product.
///
/// Passed through the whole flow (photos, checking, video) so nothing is asked
/// twice. [shop] and [contact] stay empty until the business profile exists.
class ProductDraft {
  final String name;
  final String price;

  /// Up to three short features, pointed out on the photo in the video.
  final List<String> features;
  final String category;

  /// calm | elegant | upbeat. Empty lets the server use its recommendation.
  final String mood;

  /// vertical | square.
  final String format;
  final String shop;
  final String contact;

  const ProductDraft({
    required this.name,
    this.price = '',
    this.features = const [],
    this.category = '',
    this.mood = '',
    this.format = 'vertical',
    this.shop = '',
    this.contact = '',
  });

  /// The non-empty features, trimmed.
  List<String> get cleanFeatures =>
      features.map((f) => f.trim()).where((f) => f.isNotEmpty).toList();

  Map<String, dynamic> toJson() => {
        'name': name,
        'price': price,
        'features': cleanFeatures,
        'category': category,
        'mood': mood,
        'format': format,
        'shop': shop,
        'contact': contact,
      };
}

/// One photo of the certified set: the ORIGINAL bytes that were scored, the
/// role the framework gave it, and its overall score.
class SetPhoto {
  final Uint8List bytes;
  final String role;
  final double fqs;

  const SetPhoto({required this.bytes, required this.role, required this.fqs});

  /// Role name used in saved file names.
  String get roleSlug {
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
}

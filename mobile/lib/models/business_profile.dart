import 'package:shared_preferences/shared_preferences.dart';

/// The owner's shop, entered once in "My shop" and kept on the phone
/// (shared_preferences). Nothing is stored on the server: it is sent with each
/// video plan, so the first shot and the end card carry the shop name and the
/// call to action carries the contact (v1.1.0).
class BusinessProfile {
  static const maxShop = 30;
  static const maxContact = 40;
  static const defaultColour = '#1F3A63';

  /// Eight brand colours to choose from; any "#RRGGBB" is also accepted.
  static const swatches = [
    '#1F3A63', '#2E7D32', '#8E244D', '#C2185B',
    '#E65100', '#6A1B9A', '#00838F', '#37474F',
  ];

  static final RegExp hexPattern = RegExp(r'^#[0-9A-Fa-f]{6}$');

  final String shop;
  final String contact;
  final String colour;

  /// Instagram or Facebook handle (optional), product category and a logo copied
  /// into the app's own folder (v1.5.0). Shop and contact feed the video end card.
  final String social;
  final String category;
  final String logoPath;

  const BusinessProfile({
    this.shop = '',
    this.contact = '',
    this.colour = defaultColour,
    this.social = '',
    this.category = '',
    this.logoPath = '',
  });

  /// The contact line printed on the video end card (at most [maxContact]):
  /// WhatsApp / phone, then the handle if both fit.
  String get videoContact {
    final c = contact.trim(), s = social.trim();
    if (c.isEmpty) return s.length <= maxContact ? s : s.substring(0, maxContact);
    final both = '$c · $s';
    return s.isNotEmpty && both.length <= maxContact ? both : c;
  }

  bool get isEmpty => shop.trim().isEmpty && contact.trim().isEmpty;

  static const _kShop = 'profile_shop';
  static const _kContact = 'profile_contact';
  static const _kColour = 'profile_colour';
  static const _kSocial = 'profile_social';
  static const _kCategory = 'profile_category';
  static const _kLogo = 'profile_logo';

  static Future<BusinessProfile> load() async {
    try {
      final p = await SharedPreferences.getInstance();
      final c = p.getString(_kColour) ?? defaultColour;
      return BusinessProfile(
        shop: p.getString(_kShop) ?? '',
        contact: p.getString(_kContact) ?? '',
        colour: hexPattern.hasMatch(c) ? c : defaultColour,
        social: p.getString(_kSocial) ?? '',
        category: p.getString(_kCategory) ?? '',
        logoPath: p.getString(_kLogo) ?? '',
      );
    } catch (_) {
      return const BusinessProfile();
    }
  }

  Future<bool> save() async {
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString(_kShop, shop.trim());
      await p.setString(_kContact, contact.trim());
      await p.setString(_kColour, hexPattern.hasMatch(colour) ? colour : defaultColour);
      await p.setString(_kSocial, social.trim());
      await p.setString(_kCategory, category.trim());
      await p.setString(_kLogo, logoPath);
      return true;
    } catch (_) {
      return false;
    }
  }
}

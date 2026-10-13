/// App identity shown on the About screen.
///
/// Kept in step with `version:` in pubspec.yaml by hand. There is no
/// package_info plugin, so bump BOTH when the pubspec version changes.
class AppInfo {
  static const String version = '1.0.0';
  static const String build = '1';

  /// Product name and tagline shown on the About screen.
  static const String name = 'Éclat';
  static const String tagline = 'Capture Better. Present Better.';

  /// The research attribution shown on the About screen.
  static const String attribution =
      'An app built on the Photography Quality Framework (PQF). '
      'BSc (Hons) Computing research, D J A M O Nayanaransi, '
      'NIBM / Coventry University.';
}

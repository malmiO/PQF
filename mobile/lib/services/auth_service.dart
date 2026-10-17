import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Where the account is kept. The app uses flutter_secure_storage; tests inject
/// an in-memory store.
abstract class SecureStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class FlutterSecureStore implements SecureStore {
  final FlutterSecureStorage _s = const FlutterSecureStorage();
  @override
  Future<String?> read(String key) => _s.read(key: key);
  @override
  Future<void> write(String key, String value) => _s.write(key: key, value: value);
  @override
  Future<void> delete(String key) => _s.delete(key: key);
}

class MemorySecureStore implements SecureStore {
  final Map<String, String> data = {};
  @override
  Future<String?> read(String key) async => data[key];
  @override
  Future<void> write(String key, String value) async => data[key] = value;
  @override
  Future<void> delete(String key) async => data.remove(key);
}

class AuthResult {
  final bool ok;
  final String message;
  const AuthResult(this.ok, [this.message = '']);
}

/// Prototype account, stored on this phone only (v1.5.0). There is no server user
/// database: a salted SHA-256 hash of the password is kept in secure storage and the
/// plain password is never stored. This is a prototype convenience, not a security
/// product (no lockout, no recovery).
class AuthService {
  static const minPassword = 6;
  static const storageNotice =
      'Your account is stored on this phone only. Nothing is sent to a server, '
      'and it cannot be recovered if you delete the app.';
  static const _kAccount = 'auth_account_v1';
  static const _kSignedIn = 'auth_signed_in_v1';

  final SecureStore store;
  AuthService({SecureStore? store}) : store = store ?? FlutterSecureStore();

  static final RegExp _email = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

  /// Salted SHA-256, hex: sha256(salt + ":" + password).
  static String hashPassword(String password, String salt) =>
      sha256.convert(utf8.encode('$salt:$password')).toString();

  static String newSalt([Random? rng]) {
    final r = rng ?? Random.secure();
    return base64Url.encode(List<int>.generate(16, (_) => r.nextInt(256)));
  }

  Future<Map<String, dynamic>?> _account() async {
    try {
      final raw = await store.read(_kAccount);
      return raw == null ? null : jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  Future<bool> hasAccount() async => await _account() != null;
  Future<bool> isSignedIn() async =>
      await _account() != null && await store.read(_kSignedIn) == 'true';
  Future<String> name() async => (await _account())?['name'] as String? ?? '';
  Future<String> email() async => (await _account())?['email'] as String? ?? '';

  Future<AuthResult> createAccount(String name, String email, String password) async {
    if (name.trim().isEmpty) return const AuthResult(false, 'Enter your name.');
    if (!_email.hasMatch(email.trim())) {
      return const AuthResult(false, 'Enter a valid email address.');
    }
    if (password.length < minPassword) {
      return const AuthResult(false, 'The password needs at least $minPassword characters.');
    }
    final salt = newSalt();
    await store.write(
        _kAccount,
        jsonEncode({
          'name': name.trim(),
          'email': email.trim().toLowerCase(),
          'salt': salt,
          'hash': hashPassword(password, salt),
        }));
    await store.write(_kSignedIn, 'true');
    return const AuthResult(true);
  }

  Future<AuthResult> login(String email, String password) async {
    final a = await _account();
    if (a == null) {
      return const AuthResult(false, 'No account on this phone yet. Create one first.');
    }
    final ok = a['email'] == email.trim().toLowerCase() &&
        a['hash'] == hashPassword(password, a['salt'] as String);
    if (!ok) return const AuthResult(false, 'Email or password is not right.');
    await store.write(_kSignedIn, 'true');
    return const AuthResult(true);
  }

  /// Signs out. The account stays on the phone so the owner can log in again.
  Future<void> logout() => store.delete(_kSignedIn);
}

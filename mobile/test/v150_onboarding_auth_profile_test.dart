import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/models/business_profile.dart';
import 'package:mobile/screens/onboarding_screen.dart';
import 'package:mobile/services/auth_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('onboarding flag', () {
    test('is unseen on a fresh install, seen after markSeen, and stays seen', () async {
      expect(await OnboardingScreen.seen(), isFalse);
      await OnboardingScreen.markSeen();
      expect(await OnboardingScreen.seen(), isTrue);
      expect(await OnboardingScreen.seen(), isTrue);
    });

    test('the v1.4 flag does not count: the new introduction is shown once', () async {
      SharedPreferences.setMockInitialValues({'onboarding_seen_v1': true});
      expect(await OnboardingScreen.seen(), isFalse);
    });

    testWidgets('has three pages and Skip stores the flag', (tester) async {
      await tester.pumpWidget(MaterialApp(
        routes: {'/home': (_) => const Scaffold(body: Text('home')), '/privacy': (_) => const Scaffold(body: Text('privacy'))},
        home: const OnboardingScreen(firstRun: true),
      ));
      expect(find.text('Welcome to Éclat'), findsOneWidget);
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('How it works'), findsOneWidget);
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
      expect(find.text('Set up for the best photos'), findsOneWidget);
      await tester.tap(find.text('Get started'));
      await tester.pumpAndSettle();
      expect(await OnboardingScreen.seen(), isTrue);
    });
  });

  group('account', () {
    late MemorySecureStore store;
    late AuthService auth;
    setUp(() {
      store = MemorySecureStore();
      auth = AuthService(store: store);
    });

    test('hash is salted SHA-256 and differs per salt', () {
      final h1 = AuthService.hashPassword('secret1', 'saltA');
      expect(h1, hasLength(64));
      expect(h1, isNot(AuthService.hashPassword('secret1', 'saltB')));
      expect(h1, AuthService.hashPassword('secret1', 'saltA'));
    });

    test('the plain password is never stored', () async {
      final r = await auth.createAccount('Malmi', 'Malmi@Example.com', 'hunter22');
      expect(r.ok, isTrue);
      expect(store.data.values.any((v) => v.contains('hunter22')), isFalse);
      expect(store.data['auth_account_v1'], contains('"hash"'));
      expect(store.data['auth_account_v1'], contains('"salt"'));
    });

    test('rejects a short password, bad email and empty name', () async {
      expect((await auth.createAccount('A', 'a@b.co', '12345')).ok, isFalse);
      expect((await auth.createAccount('A', 'not-an-email', '123456')).ok, isFalse);
      expect((await auth.createAccount(' ', 'a@b.co', '123456')).ok, isFalse);
      expect(await auth.hasAccount(), isFalse);
    });

    test('log in, log out, log in again; wrong password is refused', () async {
      await auth.createAccount('Malmi', 'm@x.lk', 'abcdef');
      expect(await auth.isSignedIn(), isTrue);
      await auth.logout();
      expect(await auth.isSignedIn(), isFalse);
      expect((await auth.login('m@x.lk', 'wrong!!')).ok, isFalse);
      expect(await auth.isSignedIn(), isFalse);
      expect((await auth.login(' M@X.lk ', 'abcdef')).ok, isTrue);
      expect(await auth.isSignedIn(), isTrue);
      expect(await auth.name(), 'Malmi');
    });

    test('login with no account says so', () async {
      final r = await auth.login('m@x.lk', 'abcdef');
      expect(r.ok, isFalse);
      expect(r.message, contains('No account'));
    });
  });

  group('shop profile storage', () {
    test('round trips every field on the phone', () async {
      const p = BusinessProfile(
        shop: ' Malmi Crafts ',
        contact: '0771234567',
        social: '@malmicrafts',
        category: 'Handmade',
        logoPath: '/data/logo.png',
        colour: '#2E7D32',
      );
      expect(await p.save(), isTrue);
      final q = await BusinessProfile.load();
      expect(q.shop, 'Malmi Crafts');
      expect(q.contact, '0771234567');
      expect(q.social, '@malmicrafts');
      expect(q.category, 'Handmade');
      expect(q.logoPath, '/data/logo.png');
      expect(q.colour, '#2E7D32');
    });

    test('the video contact is the phone, plus the handle when both fit in 40', () {
      expect(const BusinessProfile(contact: '0771234567', social: '@m').videoContact,
          '0771234567 · @m');
      expect(const BusinessProfile(social: '@malmicrafts').videoContact, '@malmicrafts');
      final long = BusinessProfile(contact: '0771234567', social: '@${'x' * 38}');
      expect(long.videoContact, '0771234567');
    });
  });
}

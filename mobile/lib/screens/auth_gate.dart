import 'package:flutter/material.dart';

import '../services/auth_service.dart';
import 'auth_screen.dart';
import 'business_profile_screen.dart';
import 'home_screen.dart';

/// Shows the home screen when signed in, otherwise the account screen. After a new
/// account is created the shop setup is shown once before the home screen.
class AuthGate extends StatefulWidget {
  final AuthService? auth;
  const AuthGate({super.key, this.auth});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  late final AuthService _auth = widget.auth ?? AuthService();
  bool? _signedIn;

  @override
  void initState() {
    super.initState();
    _auth.isSignedIn().then((v) {
      if (mounted) setState(() => _signedIn = v);
    });
  }

  Future<void> _done(bool created) async {
    if (created) {
      await Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => const BusinessProfileScreen(firstRun: true)));
    }
    if (mounted) setState(() => _signedIn = true);
  }

  @override
  Widget build(BuildContext context) {
    if (_signedIn == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return _signedIn! ? const HomeScreen() : AuthScreen(auth: _auth, onDone: _done);
  }
}

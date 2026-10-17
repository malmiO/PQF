import 'package:flutter/material.dart';

import '../services/auth_service.dart';

/// Create account / Log in (v1.5.0 prototype, on this phone only).
class AuthScreen extends StatefulWidget {
  final AuthService auth;

  /// Called after success; `created` is true for a new account (the shop setup follows).
  final void Function(bool created) onDone;

  const AuthScreen({super.key, required this.auth, required this.onDone});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _create = true;
  bool _hide = true;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    widget.auth.hasAccount().then((has) {
      if (mounted && has) setState(() => _create = false);
    });
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final r = _create
        ? await widget.auth.createAccount(_name.text, _email.text, _password.text)
        : await widget.auth.login(_email.text, _password.text);
    if (!mounted) return;
    if (r.ok) {
      widget.onDone(_create);
    } else {
      setState(() {
        _busy = false;
        _error = r.message;
      });
    }
  }

  InputDecoration _dec(String label) => InputDecoration(
        labelText: label,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              const SizedBox(height: 12),
              Text(_create ? 'Create your account' : 'Welcome back',
                  style: const TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                    color: const Color(0xFFEAF0F9), borderRadius: BorderRadius.circular(12)),
                child: const Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Icon(Icons.phone_android, size: 20),
                  SizedBox(width: 10),
                  Expanded(
                      child: Text(AuthService.storageNotice,
                          style: TextStyle(fontSize: 13.5, height: 1.4))),
                ]),
              ),
              const SizedBox(height: 20),
              if (_create) ...[
                TextFormField(
                  controller: _name,
                  textCapitalization: TextCapitalization.words,
                  decoration: _dec('Your name'),
                  validator: (v) => (v ?? '').trim().isEmpty ? 'Enter your name.' : null,
                ),
                const SizedBox(height: 14),
              ],
              TextFormField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                decoration: _dec('Email'),
                validator: (v) => (v ?? '').trim().isEmpty ? 'Enter your email.' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _password,
                obscureText: _hide,
                decoration: _dec(_create
                        ? 'Password (at least ${AuthService.minPassword} characters)'
                        : 'Password')
                    .copyWith(
                  suffixIcon: IconButton(
                    tooltip: _hide ? 'Show password' : 'Hide password',
                    icon: Icon(_hide ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                    onPressed: () => setState(() => _hide = !_hide),
                  ),
                ),
                validator: (v) => _create && (v ?? '').length < AuthService.minPassword
                    ? 'Use at least ${AuthService.minPassword} characters.'
                    : (v ?? '').isEmpty
                        ? 'Enter your password.'
                        : null,
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(_error!, style: const TextStyle(color: Color(0xFFB3261E))),
                ),
              const SizedBox(height: 22),
              FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                onPressed: _busy ? null : _submit,
                child: Text(_create ? 'Create account' : 'Log in'),
              ),
              const SizedBox(height: 8),
              TextButton(
                onPressed: () => setState(() {
                  _create = !_create;
                  _error = null;
                }),
                child: Text(_create ? 'I already have an account. Log in' : 'Create a new account'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

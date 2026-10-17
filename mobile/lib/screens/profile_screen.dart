import 'dart:io';

import 'package:flutter/material.dart';

import '../app_info.dart';
import '../models/business_profile.dart';
import '../services/auth_service.dart';
import 'about_screen.dart';
import 'business_profile_screen.dart';
import 'study_screens.dart';

/// Profile (v1.5.0): the account, the shop, About and Log out. Study mode stays
/// behind its PIN: a long press on the version line opens the PIN prompt.
class ProfileScreen extends StatefulWidget {
  final AuthService? auth;
  const ProfileScreen({super.key, this.auth});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late final AuthService _auth = widget.auth ?? AuthService();
  String _name = '';
  String _email = '';
  BusinessProfile _shop = const BusinessProfile();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final n = await _auth.name(), e = await _auth.email(), p = await BusinessProfile.load();
    if (!mounted) return;
    setState(() {
      _name = n;
      _email = e;
      _shop = p;
    });
  }

  Future<void> _logout() async {
    await _auth.logout();
    if (!mounted) return;
    Navigator.of(context).pushNamedAndRemoveUntil('/home', (_) => false);
  }

  @override
  Widget build(BuildContext context) {
    final logo = _shop.logoPath;
    final hasLogo = logo.isNotEmpty && File(logo).existsSync();
    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: CircleAvatar(
                radius: 28,
                backgroundImage: hasLogo ? FileImage(File(logo)) : null,
                child: hasLogo ? null : const Icon(Icons.person_outline),
              ),
              title: Text(_name.isEmpty ? 'Your account' : _name,
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              subtitle: Text(_email),
            ),
            const SizedBox(height: 6),
            Text(AuthService.storageNotice,
                style: TextStyle(fontSize: 12.5, color: Colors.grey.shade700, height: 1.4)),
            const Divider(height: 32),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.storefront_outlined),
              title: Text(_shop.shop.isEmpty ? 'Set up your shop' : _shop.shop),
              subtitle: Text(_shop.contact.isEmpty ? 'Shop details, logo and colour' : _shop.contact),
              trailing: const Icon(Icons.chevron_right),
              onTap: () async {
                await Navigator.of(context)
                    .push(MaterialPageRoute(builder: (_) => const BusinessProfileScreen()));
                _load();
              },
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.info_outline),
              title: const Text('About'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context)
                  .push(MaterialPageRoute(builder: (_) => const AboutScreen())),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(50)),
              onPressed: _logout,
              icon: const Icon(Icons.logout),
              label: const Text('Log out'),
            ),
            const SizedBox(height: 24),
            Center(
              child: GestureDetector(
                onLongPress: () => openStudyMode(context),
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Text('${AppInfo.name} ${AppInfo.version} (build ${AppInfo.build})',
                      style: TextStyle(fontSize: 12, color: Colors.grey.shade700)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

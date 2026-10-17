import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';

import '../models/business_profile.dart';
import '../widgets/help_sheet.dart';

/// "My shop": shop name, WhatsApp / phone, handle, category, logo and brand colour.
/// Shown right after the first sign-up (v1.5.0, [firstRun]) and editable from Profile.
/// The shop name and contact are printed on the video's first shot and end card.
class BusinessProfileScreen extends StatefulWidget {
  /// True when this is the shop setup that follows the first sign-up.
  final bool firstRun;
  const BusinessProfileScreen({super.key, this.firstRun = false});

  static const categories = [
    'Accessories', 'Jewellery', 'Cosmetics', 'Skincare', 'Clothing', 'Food', 'Handmade', 'Other',
  ];

  @override
  State<BusinessProfileScreen> createState() => _BusinessProfileScreenState();
}

class _BusinessProfileScreenState extends State<BusinessProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  final _shop = TextEditingController();
  final _contact = TextEditingController();
  final _social = TextEditingController();
  final _hex = TextEditingController();
  String _colour = BusinessProfile.defaultColour;
  String? _category;
  String _logoPath = '';
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    BusinessProfile.load().then((p) {
      if (!mounted) return;
      setState(() {
        _shop.text = p.shop;
        _contact.text = p.contact;
        _social.text = p.social;
        _category = BusinessProfileScreen.categories.contains(p.category) ? p.category : null;
        _logoPath = p.logoPath;
        _colour = p.colour;
        _hex.text = p.colour;
        _loading = false;
      });
    });
  }

  @override
  void dispose() {
    _shop.dispose();
    _contact.dispose();
    _social.dispose();
    _hex.dispose();
    super.dispose();
  }

  static Color _toColor(String hex) =>
      Color(int.parse(hex.substring(1), radix: 16) | 0xFF000000);

  void _pick(String hex) => setState(() {
        _colour = hex.toUpperCase();
        _hex.text = _colour;
      });

  /// Chooses a logo from the gallery and keeps a copy in the app's own folder, so it
  /// survives the original being moved or deleted.
  Future<void> _pickLogo() async {
    try {
      final f = await ImagePicker()
          .pickImage(source: ImageSource.gallery, maxWidth: 800, maxHeight: 800);
      if (f == null) return;
      final dir = await getApplicationDocumentsDirectory();
      final ext = f.path.toLowerCase().endsWith('.png') ? 'png' : 'jpg';
      final dest = File('${dir.path}/shop_logo.$ext');
      await dest.writeAsBytes(await f.readAsBytes(), flush: true);
      await FileImage(dest).evict();
      if (mounted) setState(() => _logoPath = dest.path);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Could not use that image.')));
      }
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    final ok = await BusinessProfile(
      shop: _shop.text,
      contact: _contact.text,
      social: _social.text,
      category: _category ?? '',
      logoPath: _logoPath,
      colour: _colour,
    ).save();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(ok ? 'Saved. Your videos will show your shop.' : 'Could not save.')));
    if (ok) Navigator.of(context).pop(true);
  }

  InputDecoration _dec(String label, String hint) => InputDecoration(
        labelText: label,
        hintText: hint,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.firstRun ? 'Set up your shop' : 'My shop'),
        automaticallyImplyLeading: !widget.firstRun,
        actions: const [HelpButton(HelpTopic.profile)],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : Form(
                key: _formKey,
                child: ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    Text(
                        widget.firstRun
                            ? 'Tell us about your shop. It appears at the start and the '
                                'end of every video. You can change this later in Profile.'
                            : 'Shown at the start and the end of every video.',
                        style: TextStyle(fontSize: 14, color: Colors.grey.shade700)),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _shop,
                      maxLength: BusinessProfile.maxShop,
                      textCapitalization: TextCapitalization.words,
                      decoration: _dec('Shop name (required)', 'Malmi Crafts'),
                      validator: (v) =>
                          (v ?? '').trim().isEmpty ? 'Enter your shop name.' : null,
                    ),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _contact,
                      maxLength: BusinessProfile.maxContact,
                      keyboardType: TextInputType.phone,
                      decoration: _dec('WhatsApp / phone', '077 123 4567'),
                    ),
                    const SizedBox(height: 6),
                    TextFormField(
                      controller: _social,
                      maxLength: BusinessProfile.maxContact,
                      decoration: _dec('Instagram / Facebook (optional)', '@malmicrafts'),
                    ),
                    const SizedBox(height: 6),
                    DropdownButtonFormField<String>(
                      initialValue: _category,
                      decoration: _dec('Product category', ''),
                      items: [
                        for (final c in BusinessProfileScreen.categories)
                          DropdownMenuItem(value: c, child: Text(c)),
                      ],
                      onChanged: (v) => setState(() => _category = v),
                    ),
                    const SizedBox(height: 16),
                    Row(children: [
                      _LogoThumb(path: _logoPath),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Wrap(spacing: 8, children: [
                          OutlinedButton.icon(
                            onPressed: _pickLogo,
                            icon: const Icon(Icons.image_outlined, size: 20),
                            label: Text(_logoPath.isEmpty ? 'Add logo (optional)' : 'Change logo'),
                          ),
                          if (_logoPath.isNotEmpty)
                            TextButton(
                                onPressed: () => setState(() => _logoPath = ''),
                                child: const Text('Remove')),
                        ]),
                      ),
                    ]),
                    const SizedBox(height: 18),
                    const Text('Brand colour',
                        style: TextStyle(fontSize: 16.5, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        for (final hex in BusinessProfile.swatches)
                          Semantics(
                            button: true,
                            selected: hex == _colour,
                            label: 'Colour $hex',
                            child: InkWell(
                              onTap: () => _pick(hex),
                              customBorder: const CircleBorder(),
                              child: Container(
                                width: 48,
                                height: 48,
                                decoration: BoxDecoration(
                                  color: _toColor(hex),
                                  shape: BoxShape.circle,
                                  border: Border.all(
                                      color: hex == _colour ? Colors.black : Colors.white,
                                      width: 3),
                                ),
                                child: hex == _colour
                                    ? const Icon(Icons.check, color: Colors.white)
                                    : null,
                              ),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _hex,
                      maxLength: 7,
                      decoration: _dec('Or a colour code', '#1F3A63'),
                      validator: (v) => BusinessProfile.hexPattern.hasMatch(v ?? '')
                          ? null
                          : 'Use the form #RRGGBB, for example #1F3A63.',
                      onChanged: (v) {
                        if (BusinessProfile.hexPattern.hasMatch(v)) {
                          setState(() => _colour = v.toUpperCase());
                        }
                      },
                    ),
                    const SizedBox(height: 20),
                    FilledButton(
                      style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                      onPressed: _save,
                      child: Text(widget.firstRun ? 'Save and continue' : 'Save'),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}

class _LogoThumb extends StatelessWidget {
  final String path;
  const _LogoThumb({required this.path});

  @override
  Widget build(BuildContext context) {
    final ok = path.isNotEmpty && File(path).existsSync();
    return Container(
      width: 64,
      height: 64,
      decoration: BoxDecoration(
        color: Colors.grey.shade200,
        borderRadius: BorderRadius.circular(12),
        image: ok ? DecorationImage(image: FileImage(File(path)), fit: BoxFit.cover) : null,
      ),
      child: ok ? null : Icon(Icons.storefront_outlined, color: Colors.grey.shade600),
    );
  }
}

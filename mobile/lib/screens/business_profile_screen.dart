import 'package:flutter/material.dart';

import '../models/business_profile.dart';
import '../widgets/help_sheet.dart';

/// "My shop": the shop name, contact and brand colour used in every video.
class BusinessProfileScreen extends StatefulWidget {
  const BusinessProfileScreen({super.key});

  @override
  State<BusinessProfileScreen> createState() => _BusinessProfileScreenState();
}

class _BusinessProfileScreenState extends State<BusinessProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  final _shop = TextEditingController();
  final _contact = TextEditingController();
  final _hex = TextEditingController();
  String _colour = BusinessProfile.defaultColour;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    BusinessProfile.load().then((p) {
      if (!mounted) return;
      setState(() {
        _shop.text = p.shop;
        _contact.text = p.contact;
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
    _hex.dispose();
    super.dispose();
  }

  static Color _toColor(String hex) =>
      Color(int.parse(hex.substring(1), radix: 16) | 0xFF000000);

  void _pick(String hex) => setState(() {
        _colour = hex.toUpperCase();
        _hex.text = _colour;
      });

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    final ok = await BusinessProfile(
      shop: _shop.text,
      contact: _contact.text,
      colour: _colour,
    ).save();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(ok ? 'Saved. Your videos will show your shop.' : 'Could not save.')));
    if (ok) Navigator.of(context).pop();
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
        title: const Text('My shop'),
        actions: const [HelpButton(HelpTopic.profile)],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: _formKey,
              child: ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  Text('Shown at the start and the end of every video.',
                      style: TextStyle(fontSize: 14, color: Colors.grey.shade700)),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _shop,
                    maxLength: BusinessProfile.maxShop,
                    textCapitalization: TextCapitalization.words,
                    decoration: _dec('Shop name', 'Malmi Crafts'),
                  ),
                  const SizedBox(height: 6),
                  TextFormField(
                    controller: _contact,
                    maxLength: BusinessProfile.maxContact,
                    decoration: _dec('Contact', 'Phone, WhatsApp or @instagram'),
                  ),
                  const SizedBox(height: 14),
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
                    child: const Text('Save'),
                  ),
                ],
              ),
            ),
    );
  }
}

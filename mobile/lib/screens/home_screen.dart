import 'package:flutter/material.dart';
import '../config/api_config.dart';
import '../services/pqf_api.dart';
import 'capture_screen.dart';

/// Entry point. Kept deliberately short, because every screen before the camera
/// is a screen between the seller and the thing they came to do.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _controller = TextEditingController();
  final _api = PqfApi();
  bool? _serverUp;
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _checkServer();
  }

  Future<void> _checkServer() async {
    setState(() => _checking = true);
    final ok = await _api.health();
    if (mounted) setState(() { _serverUp = ok; _checking = false; });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        // LayoutBuilder plus a scroll view means the screen survives a small
        // display, a large system font, or an on screen keyboard, none of which
        // a fixed Column with a Spacer tolerates.
        child: LayoutBuilder(
          builder: (context, constraints) {
            return SingleChildScrollView(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: IntrinsicHeight(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const SizedBox(height: 24),
                        const Text('Product Photo Assistant',
                            style: TextStyle(
                                fontSize: 27, fontWeight: FontWeight.bold)),
                        const SizedBox(height: 10),
                        Text(
                          'Take product photos that are ready to post. '
                          'The app checks each shot as you take it.',
                          style: TextStyle(
                              fontSize: 15.5,
                              color: Colors.grey.shade700,
                              height: 1.4),
                        ),
                        const SizedBox(height: 30),
                        TextField(
                          controller: _controller,
                          textCapitalization: TextCapitalization.words,
                          decoration: InputDecoration(
                            labelText: 'What are you photographing?',
                            hintText: 'For example, silver bracelet',
                            border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(12)),
                          ),
                        ),
                        const SizedBox(height: 20),
                        _ServerStatus(
                          checking: _checking,
                          up: _serverUp,
                          onRetry: _checkServer,
                        ),
                        const Expanded(child: SizedBox(height: 24)),
                        FilledButton(
                          onPressed: _serverUp == true
                              ? () {
                                  final name = _controller.text.trim();
                                  Navigator.of(context).push(MaterialPageRoute(
                                    builder: (_) => CaptureScreen(
                                      productName:
                                          name.isEmpty ? 'Product' : name,
                                    ),
                                  ));
                                }
                              : null,
                          child: const Text('Start photographing'),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          'Tip. Use a plain white or light surface, and natural '
                          'light from a window rather than overhead lighting.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                              fontSize: 13,
                              color: Colors.grey.shade600,
                              height: 1.4),
                        ),
                        const SizedBox(height: 8),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _ServerStatus extends StatelessWidget {
  final bool checking;
  final bool? up;
  final VoidCallback onRetry;

  const _ServerStatus({required this.checking, required this.up, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    if (checking) {
      return Row(children: const [
        SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
        SizedBox(width: 12),
        Text('Connecting'),
      ]);
    }
    final ok = up == true;
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: ok ? const Color(0xFFEAF4EC) : const Color(0xFFFDECEA),
        borderRadius: BorderRadius.circular(11),
      ),
      child: Row(children: [
        Icon(ok ? Icons.check_circle : Icons.error_outline,
            color: ok ? const Color(0xFF2E7D32) : const Color(0xFFC62828), size: 20),
        const SizedBox(width: 11),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                ok
                    ? 'Connected and ready'
                    : 'Cannot reach the scoring service. Check that the server '
                      'is running and that the address below is correct.',
                style: const TextStyle(fontSize: 13.5, height: 1.35),
              ),
              const SizedBox(height: 3),
              Text(
                ApiConfig.displayTarget,
                style: TextStyle(
                    fontSize: 11.5,
                    color: Colors.grey.shade600,
                    fontFamily: 'monospace'),
              ),
            ],
          ),
        ),
        if (!ok)
          TextButton(onPressed: onRetry, child: const Text('Retry')),
      ]),
    );
  }
}

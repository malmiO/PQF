import 'dart:async';
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../services/pqf_api.dart';
import '../services/frame_converter.dart';
import '../widgets/guidance_overlay.dart';
import 'results_screen.dart';

/// Guided capture.
///
/// The loop is deliberately throttled. Frames arrive from the camera far faster
/// than they can usefully be checked, so only one frame per interval is sent,
/// and a new frame is never sent while a previous check is still in flight.
/// Without that guard the queue grows and guidance falls behind reality, which
/// is worse than no guidance at all because it corrects a shot the user has
/// already fixed.
class CaptureScreen extends StatefulWidget {
  final String productName;

  const CaptureScreen({super.key, required this.productName});

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen>
    with WidgetsBindingObserver {
  CameraController? _controller;
  final PqfApi _api = PqfApi();

  GuidanceResult _guidance = GuidanceResult.empty();
  bool _checkInFlight = false;
  DateTime _lastCheck = DateTime.fromMillisecondsSinceEpoch(0);

  final List<Uint8List> _captured = [];
  bool _initialising = true;
  bool _scoring = false;
  String? _error;

  /// The gate expects a set of four to six images, so the target is shown to
  /// the user rather than left implicit.
  static const int targetShots = 5;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _startCamera();
  }

  Future<void> _startCamera() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        setState(() {
          _error = 'No camera found on this device.';
          _initialising = false;
        });
        return;
      }

      final back = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );

      // High for the captured photograph. The guidance frames are reduced
      // separately, so preview quality does not have to be compromised.
      final controller = CameraController(
        back,
        ResolutionPreset.high,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.yuv420,
      );

      await controller.initialize();
      if (!mounted) return;

      _controller = controller;
      setState(() => _initialising = false);

      await controller.startImageStream(_onFrame);
    } catch (e) {
      setState(() {
        _error = 'Could not start the camera. $e';
        _initialising = false;
      });
    }
  }

  /// Called for every camera frame. Almost all are discarded.
  void _onFrame(CameraImage image) {
    if (_checkInFlight || _scoring) return;
    final now = DateTime.now();
    if (now.difference(_lastCheck) < ApiConfig.guidanceInterval) return;

    _lastCheck = now;
    _checkInFlight = true;

    // Conversion runs off the UI thread so the preview stays smooth.
    compute(FrameConverter.convert, FramePayload.fromCameraImage(image))
        .then((jpeg) => _api.guidance(jpeg))
        .then((result) {
      if (!mounted) return;
      if (result != null) setState(() => _guidance = result);
    }).whenComplete(() => _checkInFlight = false);
  }

  Future<void> _capture() async {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) return;

    try {
      // The stream must pause while a still is taken.
      await controller.stopImageStream();
      final file = await controller.takePicture();
      final bytes = await file.readAsBytes();

      setState(() => _captured.add(bytes));

      if (mounted) await controller.startImageStream(_onFrame);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Capture failed. $e')),
        );
      }
    }
  }

  Future<void> _finish() async {
    if (_captured.length < 2) return;
    setState(() => _scoring = true);

    try {
      await _controller?.stopImageStream();
      final result = await _api.batch(_captured);
      if (!mounted) return;

      await Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => ResultsScreen(
          productName: widget.productName,
          result: result,
          images: _captured,
        ),
      ));

      if (mounted) {
        setState(() => _scoring = false);
        await _controller?.startImageStream(_onFrame);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _scoring = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not score the images. $e')),
      );
      await _controller?.startImageStream(_onFrame);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    if (state == AppLifecycleState.inactive) {
      c.dispose();
    } else if (state == AppLifecycleState.resumed) {
      _startCamera();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_initialising) {
      return const Scaffold(
        backgroundColor: Colors.black,
        body: Center(child: CircularProgressIndicator()),
      );
    }
    if (_error != null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Capture')),
        body: Padding(
          padding: const EdgeInsets.all(24),
          child: Center(child: Text(_error!, textAlign: TextAlign.center)),
        ),
      );
    }

    final controller = _controller!;
    final enough = _captured.length >= 2;

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          CameraPreview(controller),
          const FramingGuide(),

          // Product name and shot count.
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Flexible(
                    child: Text(
                      widget.productName,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        shadows: [Shadow(color: Colors.black87, blurRadius: 5)],
                      ),
                    ),
                  ),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.55),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Text(
                      '${_captured.length} of $targetShots',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),

          // Guidance and controls.
          Align(
            alignment: Alignment.bottomCenter,
            child: SafeArea(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 22),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    GuidanceOverlay(
                      guidance: _guidance,
                      waitingForServer: _checkInFlight,
                    ),
                    const SizedBox(height: 22),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                      children: [
                        SizedBox(
                          width: 86,
                          child: _captured.isEmpty
                              ? const SizedBox.shrink()
                              : TextButton(
                                  onPressed: () =>
                                      setState(() => _captured.removeLast()),
                                  child: const Text('Undo',
                                      style: TextStyle(color: Colors.white)),
                                ),
                        ),
                        _ShutterButton(
                          ready: _guidance.ready,
                          onPressed: _scoring ? null : _capture,
                        ),
                        SizedBox(
                          width: 86,
                          child: enough
                              ? TextButton(
                                  onPressed: _scoring ? null : _finish,
                                  child: Text(
                                    _scoring ? 'Scoring' : 'Done',
                                    style: const TextStyle(
                                      color: Colors.white,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                )
                              : const SizedBox.shrink(),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),

          if (_scoring)
            Container(
              color: Colors.black54,
              child: const Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: Colors.white),
                    SizedBox(height: 18),
                    Text('Checking your photos',
                        style: TextStyle(color: Colors.white, fontSize: 16)),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// The shutter.
///
/// It is never disabled when guidance is failing. The framework advises, it does
/// not forbid, and a user who is deliberately capturing a difficult shot should
/// not be locked out of their own camera. The ring turns green when the checks
/// pass, which communicates readiness without removing control.
class _ShutterButton extends StatelessWidget {
  final bool ready;
  final VoidCallback? onPressed;

  const _ShutterButton({required this.ready, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onPressed,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        width: 78,
        height: 78,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(
            color: ready ? const Color(0xFF2E7D32) : Colors.white70,
            width: 5,
          ),
        ),
        child: Center(
          child: Container(
            width: 58,
            height: 58,
            decoration: const BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
            ),
          ),
        ),
      ),
    );
  }
}

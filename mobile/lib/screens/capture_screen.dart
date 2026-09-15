import 'dart:async';
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../models/api_result.dart';
import '../models/shot_plan.dart';
import '../services/pqf_api.dart';
import '../services/frame_converter.dart';
import '../widgets/guidance_overlay.dart';
import '../widgets/error_view.dart';
import 'results_screen.dart';

/// Guided capture.
///
/// Three behaviours matter beyond showing a camera.
///
/// The shot plan walks the user through the coverage the quality gate requires,
/// so a set is not rejected at the end for missing a view the user never knew
/// they needed.
///
/// Auto capture fires only after the checks pass for several consecutive
/// frames, which is a stability signal. A single passing frame can occur mid
/// wobble. Sustained passing frames mean the phone is genuinely still.
///
/// Guidance failures never interrupt the camera. A dropped frame keeps the
/// previous reading, and only a sustained failure is surfaced.
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

  /// Releases the in flight guard if a check never completes. Without this, one
  /// hung conversion or request freezes guidance permanently, which is exactly
  /// what happened before the converter was made cheap enough to finish.
  Timer? _watchdog;
  static const Duration watchdogTimeout = Duration(seconds: 6);

  final List<Uint8List> _captured = [];
  int _step = 0;

  bool _autoCapture = true;
  int _stableFrames = 0;
  bool _capturing = false;

  /// Consecutive passing frames before auto capture fires. At the default
  /// interval this is roughly two seconds of steady framing, long enough to
  /// exclude a momentary pass during movement.
  static const int stableFramesNeeded = 3;

  bool _scoring = false;
  bool _initialising = true;
  String? _cameraError;

  int _guidanceFailures = 0;
  static const int failuresBeforeWarning = 5;
  bool _warnedAboutConnection = false;

  String? _confirmation;
  Timer? _confirmationTimer;

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
          _cameraError = 'No camera was found on this phone.';
          _initialising = false;
        });
        return;
      }
      final back = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
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
    } on CameraException catch (e) {
      setState(() {
        _cameraError = e.code == 'CameraAccessDenied'
            ? 'Camera permission was refused. Allow camera access for this app '
                'in your phone settings, then come back.'
            : 'The camera could not start. ${e.description ?? e.code}';
        _initialising = false;
      });
    } catch (e) {
      setState(() {
        _cameraError = 'The camera could not start.';
        _initialising = false;
      });
      debugPrint('Camera start failed. $e');
    }
  }

  void _onFrame(CameraImage image) {
    if (_checkInFlight || _scoring || _capturing) return;
    final now = DateTime.now();
    if (now.difference(_lastCheck) < ApiConfig.guidanceInterval) return;

    _lastCheck = now;
    _checkInFlight = true;

    // Release the guard if a check never completes. Without this, one hung
    // conversion or request freezes guidance permanently, which is what made
    // the indicators appear stuck on "checking the shot".
    _watchdog?.cancel();
    _watchdog = Timer(watchdogTimeout, () {
      if (_checkInFlight) {
        debugPrint('Guidance check timed out. Releasing so the loop recovers.');
        _checkInFlight = false;
      }
    });

    compute(FrameConverter.convert, FramePayload.fromCameraImage(image))
        .then((jpeg) => _api.guidance(jpeg))
        .then(_applyGuidance)
        .catchError((Object e) => debugPrint('Guidance frame failed. $e'))
        .whenComplete(() {
      _watchdog?.cancel();
      _checkInFlight = false;
    });
  }

  void _applyGuidance(ApiResult<GuidanceResult> result) {
    if (!mounted) return;

    if (!result.ok) {
      // A dropped frame keeps the previous reading rather than blanking the
      // indicators, which would make the interface flicker on a weak network.
      _guidanceFailures++;
      if (_guidanceFailures >= failuresBeforeWarning && !_warnedAboutConnection) {
        _warnedAboutConnection = true;
        ErrorView.showSnack(context, result.failure!);
      }
      return;
    }

    _guidanceFailures = 0;
    _warnedAboutConnection = false;
    final g = result.value!;

    setState(() {
      _guidance = g;
      _stableFrames = g.ready ? _stableFrames + 1 : 0;
    });

    if (_autoCapture &&
        _stableFrames >= stableFramesNeeded &&
        !_capturing &&
        _step < ShotPlan.steps.length) {
      _capture(auto: true);
    }
  }

  Future<void> _capture({bool auto = false}) async {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized || _capturing) {
      return;
    }
    setState(() {
      _capturing = true;
      _stableFrames = 0;
    });

    // Let any in flight guidance settle before touching the stream. Stopping
    // the stream while a conversion is running is what produced the repeated
    // "that photo could not be taken" failures.
    var waited = 0;
    while (_checkInFlight && waited < 1500) {
      await Future<void>.delayed(const Duration(milliseconds: 50));
      waited += 50;
    }

    try {
      await controller.stopImageStream();
      final file = await controller.takePicture();
      final bytes = await file.readAsBytes();
      if (!mounted) return;

      setState(() {
        _captured.add(bytes);
        _step = _captured.length;
        _confirmation = ShotPlan.confirmation(_captured.length);
      });

      _confirmationTimer?.cancel();
      _confirmationTimer = Timer(const Duration(milliseconds: 2600), () {
        if (mounted) setState(() => _confirmation = null);
      });

      if (mounted) await controller.startImageStream(_onFrame);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('That photo could not be taken. Try again.')),
      );
      debugPrint('Capture failed. $e');
      try {
        await controller.startImageStream(_onFrame);
      } catch (_) {}
    } finally {
      if (mounted) setState(() => _capturing = false);
    }
  }

  Future<void> _finish() async {
    if (_captured.length < 2) return;
    setState(() => _scoring = true);

    try {
      await _controller?.stopImageStream();
    } catch (_) {}

    final result = await _api.batch(_captured);
    if (!mounted) return;

    if (!result.ok) {
      setState(() => _scoring = false);
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          content: ErrorView(
            failure: result.failure!,
            onDismiss: () => Navigator.of(context).pop(),
            onRetry: () {
              Navigator.of(context).pop();
              _finish();
            },
          ),
        ),
      );
      try {
        await _controller?.startImageStream(_onFrame);
      } catch (_) {}
      return;
    }

    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => ResultsScreen(
        productName: widget.productName,
        result: result.value!,
        images: _captured,
      ),
    ));

    if (mounted) {
      setState(() => _scoring = false);
      try {
        await _controller?.startImageStream(_onFrame);
      } catch (_) {}
    }
  }

  void _undo() {
    if (_captured.isEmpty) return;
    setState(() {
      _captured.removeLast();
      _step = _captured.length;
      _confirmation = null;
    });
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
    _watchdog?.cancel();
    _confirmationTimer?.cancel();
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
    if (_cameraError != null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Camera')),
        body: Padding(
          padding: const EdgeInsets.all(22),
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.videocam_off, size: 46, color: Colors.grey),
                const SizedBox(height: 16),
                Text(_cameraError!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 15.5, height: 1.4)),
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: () {
                    setState(() {
                      _cameraError = null;
                      _initialising = true;
                    });
                    _startCamera();
                  },
                  child: const Text('Try again'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final controller = _controller!;
    final done = _captured.length;
    final step = ShotPlan.at(_step);
    final canFinish = ShotPlan.isComplete(done);

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          CameraPreview(controller),
          const FramingGuide(),
          SafeArea(
            child: Column(
              children: [
                _TopBar(
                  productName: widget.productName,
                  autoCapture: _autoCapture,
                  onToggleAuto: () =>
                      setState(() => _autoCapture = !_autoCapture),
                ),
                const SizedBox(height: 8),
                _ShotProgress(captured: done),
                const Spacer(),
                if (_confirmation != null)
                  _Confirmation(text: _confirmation!)
                else
                  _ShotInstruction(
                      step: step, optional: ShotPlan.isOptional(_step)),
                const SizedBox(height: 14),
                GuidanceOverlay(
                  guidance: _guidance,
                  waitingForServer: _checkInFlight,
                ),
                const SizedBox(height: 18),
                _Controls(
                  canUndo: done > 0,
                  canFinish: canFinish,
                  ready: _guidance.ready,
                  autoCapture: _autoCapture,
                  stableProgress: _stableFrames / stableFramesNeeded,
                  busy: _scoring || _capturing,
                  onUndo: _undo,
                  onCapture: () => _capture(),
                  onFinish: _finish,
                ),
                const SizedBox(height: 18),
              ],
            ),
          ),
          if (_scoring)
            Container(
              color: Colors.black.withOpacity(0.72),
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const CircularProgressIndicator(color: Colors.white),
                    const SizedBox(height: 18),
                    const Text('Checking your photos',
                        style: TextStyle(color: Colors.white, fontSize: 16.5)),
                    const SizedBox(height: 6),
                    Text('This takes a few seconds per photo',
                        style: TextStyle(
                            color: Colors.white.withOpacity(0.75),
                            fontSize: 13)),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  final String productName;
  final bool autoCapture;
  final VoidCallback onToggleAuto;

  const _TopBar({
    required this.productName,
    required this.autoCapture,
    required this.onToggleAuto,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      child: Row(children: [
        Expanded(
          child: Text(
            productName,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 15.5,
              fontWeight: FontWeight.w600,
              shadows: [Shadow(color: Colors.black87, blurRadius: 5)],
            ),
          ),
        ),
        // Auto capture is a user choice, not something imposed. Someone
        // photographing a difficult item may want full manual control.
        GestureDetector(
          onTap: onToggleAuto,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
            decoration: BoxDecoration(
              color: Colors.black.withOpacity(0.55),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(autoCapture ? Icons.motion_photos_auto : Icons.touch_app,
                  color: Colors.white, size: 16),
              const SizedBox(width: 6),
              Text(autoCapture ? 'Auto' : 'Manual',
                  style:
                      const TextStyle(color: Colors.white, fontSize: 12.5)),
            ]),
          ),
        ),
      ]),
    );
  }
}

/// Progress strip showing which shots are done and which remain.
class _ShotProgress extends StatelessWidget {
  final int captured;

  const _ShotProgress({required this.captured});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(ShotPlan.steps.length, (i) {
        final done = i < captured;
        final current = i == captured;
        return Container(
          margin: const EdgeInsets.symmetric(horizontal: 3),
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
          decoration: BoxDecoration(
            color: done
                ? const Color(0xFF2E7D32)
                : current
                    ? Colors.white.withOpacity(0.92)
                    : Colors.black.withOpacity(0.42),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            if (done)
              const Padding(
                padding: EdgeInsets.only(right: 4),
                child: Icon(Icons.check, size: 12, color: Colors.white),
              ),
            Text(
              ShotPlan.steps[i].label,
              style: TextStyle(
                fontSize: 11,
                fontWeight: current ? FontWeight.w700 : FontWeight.w500,
                color: current ? const Color(0xFF1F3A63) : Colors.white,
              ),
            ),
          ]),
        );
      }),
    );
  }
}

class _ShotInstruction extends StatelessWidget {
  final ShotStep step;
  final bool optional;

  const _ShotInstruction({required this.step, required this.optional});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 20),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.72),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Text(
          optional
              ? 'Optional'
              : 'Now take the ${step.label.toLowerCase()} shot',
          style: TextStyle(
            color: Colors.white.withOpacity(0.85),
            fontSize: 12,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.4,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          step.instruction,
          textAlign: TextAlign.center,
          style: const TextStyle(
              color: Colors.white,
              fontSize: 15.5,
              fontWeight: FontWeight.w600,
              height: 1.3),
        ),
        const SizedBox(height: 5),
        Text(
          step.why,
          textAlign: TextAlign.center,
          style: TextStyle(
              color: Colors.white.withOpacity(0.78),
              fontSize: 12.5,
              height: 1.3),
        ),
      ]),
    );
  }
}

class _Confirmation extends StatelessWidget {
  final String text;

  const _Confirmation({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 24),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      decoration: BoxDecoration(
        color: const Color(0xFF2E7D32).withOpacity(0.94),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.check_circle, color: Colors.white, size: 21),
        const SizedBox(width: 11),
        Flexible(
          child: Text(text,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 15.5,
                  fontWeight: FontWeight.w600,
                  height: 1.3)),
        ),
      ]),
    );
  }
}

class _Controls extends StatelessWidget {
  final bool canUndo;
  final bool canFinish;
  final bool ready;
  final bool autoCapture;
  final double stableProgress;
  final bool busy;
  final VoidCallback onUndo;
  final VoidCallback onCapture;
  final VoidCallback onFinish;

  const _Controls({
    required this.canUndo,
    required this.canFinish,
    required this.ready,
    required this.autoCapture,
    required this.stableProgress,
    required this.busy,
    required this.onUndo,
    required this.onCapture,
    required this.onFinish,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
      children: [
        SizedBox(
          width: 88,
          child: canUndo
              ? TextButton(
                  onPressed: busy ? null : onUndo,
                  child:
                      const Text('Undo', style: TextStyle(color: Colors.white)),
                )
              : const SizedBox.shrink(),
        ),
        _Shutter(
          ready: ready,
          autoCapture: autoCapture,
          progress: stableProgress.clamp(0.0, 1.0),
          onPressed: busy ? null : onCapture,
        ),
        SizedBox(
          width: 88,
          child: canFinish
              ? TextButton(
                  onPressed: busy ? null : onFinish,
                  child: Text(busy ? 'Wait' : 'Done',
                      style: const TextStyle(
                          color: Colors.white, fontWeight: FontWeight.w700)),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }
}

/// The shutter, with a ring that fills as the shot holds steady.
///
/// It is never disabled when guidance is failing. The framework advises, it
/// does not forbid, and a user photographing something deliberately unusual
/// should keep control of their own camera.
class _Shutter extends StatelessWidget {
  final bool ready;
  final bool autoCapture;
  final double progress;
  final VoidCallback? onPressed;

  const _Shutter({
    required this.ready,
    required this.autoCapture,
    required this.progress,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onPressed,
      child: SizedBox(
        width: 84,
        height: 84,
        child: Stack(alignment: Alignment.center, children: [
          if (autoCapture && progress > 0)
            SizedBox(
              width: 84,
              height: 84,
              child: CircularProgressIndicator(
                value: progress,
                strokeWidth: 5,
                color: const Color(0xFF2E7D32),
                backgroundColor: Colors.white24,
              ),
            ),
          AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: 74,
            height: 74,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(
                color: ready ? const Color(0xFF2E7D32) : Colors.white70,
                width: 4,
              ),
            ),
            child: Center(
              child: Container(
                width: 56,
                height: 56,
                decoration: const BoxDecoration(
                    color: Colors.white, shape: BoxShape.circle),
              ),
            ),
          ),
        ]),
      ),
    );
  }
}

import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image/image.dart' as img;

import '../models/api_result.dart';
import '../models/auto_zoom.dart';
import '../models/shot_plan.dart';
import '../services/pqf_api.dart';
import '../services/frame_converter.dart';
import '../widgets/guidance_overlay.dart';
import '../widgets/shot_card.dart';
import '../widgets/confirm_leave.dart';
import '../widgets/error_view.dart';
import '../widgets/help_sheet.dart';
import '../models/study_session.dart';
import '../services/study_data.dart';
import '../services/study_log.dart';
import 'results_screen.dart';
import 'study_screens.dart';

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
  final ProductDraft draft;

  /// The shots to take. Null means the full [ShotPlan.steps]; otherwise only
  /// these (the missing shots), all of them required.
  final List<ShotStep>? plan;

  /// When true, Done returns the captured photos to the caller (the results
  /// screen checks them together with the photos that already passed) instead
  /// of checking them here.
  final bool returnPhotos;

  const CaptureScreen({
    super.key,
    required this.draft,
    this.plan,
    this.returnPhotos = false,
  });

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen>
    with WidgetsBindingObserver {
  List<ShotStep> get _steps => widget.plan ?? ShotPlan.steps;
  int get _required =>
      widget.plan == null ? ShotPlan.requiredCount : widget.plan!.length;
  ShotStep _stepAt(int i) => _steps[i.clamp(0, _steps.length - 1)];

  /// False only in the UNGUIDED study condition (v1.1.0): no /guidance calls,
  /// no overlay, no briefings, no auto-capture. Same crop, resolution, zoom.
  bool get _guided => GuidancePolicy.guided(StudySession.current);

  CameraController? _controller;
  final PqfApi _api = PqfApi();

  GuidanceResult _guidance = GuidanceResult.empty();
  bool _checkInFlight = false;
  DateTime _lastCheck = DateTime.fromMillisecondsSinceEpoch(0);

  /// Logs the decoded guidance frame's dimensions exactly once, to confirm
  /// whether the camera delivers frames upright or in sensor orientation.
  bool _loggedFrameDims = false;

  // --- Exposure assist (2026-10-05) -------------------------------------
  /// Current exposure compensation applied to the camera, in EV. A grey
  /// lightbox background is fixed by raising this, the step a photographer
  /// does by hand, so the app nudges it when the server hints and offers a
  /// manual slider for the same control.
  double _exposureOffset = 0.0;
  double _minExposure = 0.0;
  double _maxExposure = 0.0;
  bool _exposureSupported = false;

  // --- Zoom (2026-10-06) ------------------------------------------------
  /// Camera zoom, shown as a slider like brightness. Lets the owner fill the
  /// frame (a small item, a detail shot) without moving the phone closer and
  /// losing focus. Digital zoom crops the sensor, so it is capped at
  /// [maxZoomCap]: beyond that the photo gets soft and fails the sharpness check.
  double _zoom = 1.0;
  double _minZoom = 1.0;
  double _maxZoom = 1.0;
  bool _zoomSupported = false;
  static const double maxZoomCap = 3.0;

  // Auto zoom (v1.1.0): follows the server's zoom hint while Auto is on.
  DateTime _lastZoomChange = DateTime.fromMillisecondsSinceEpoch(0);
  DateTime _lastAutoZoom = DateTime.fromMillisecondsSinceEpoch(0);

  /// The owner moved the zoom slider during this shot: auto zoom stays out.
  bool _manualZoomThisShot = false;

  /// The current zoom was chosen by auto zoom (shown on the slider label).
  bool _zoomIsAuto = false;

  /// The highest zoom that keeps enough real detail on this camera
  /// (AutoZoom.capFor); auto zoom stays below it, the label warns above it.
  double _detailZoomCap = AutoZoom.autoCap;

  /// One automatic exposure step every this long, so it does not oscillate.
  static const double exposureStepEv = 0.3;
  static const Duration exposureStepInterval = Duration(milliseconds: 1500);
  DateTime _lastExposureStep = DateTime.fromMillisecondsSinceEpoch(0);

  /// Prints timing and scores for every guidance check. Leave on until the
  /// loop is confirmed working on a real device, then turn off.
  static const bool _diagnostics = true;

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

  /// A captured frame whose mean brightness (0..255) is below this is treated
  /// as black and never sent for scoring.
  static const int blackFrameThreshold = 20;

  bool _scoring = false;

  /// Study mode: own picks were made for this capture (asked once).
  bool _picksDone = false;
  bool _initialising = true;
  String? _cameraError;

  int _guidanceFailures = 0;
  static const int failuresBeforeWarning = 5;
  bool _warnedAboutConnection = false;

  String? _confirmation;
  Timer? _confirmationTimer;

  /// Whether the briefing for the current shot is showing.
  ///
  /// The briefing explains the shot with the camera idle behind it, so the user
  /// reads one thing at a time. Previously the instruction, its reason, four
  /// indicators and a correction were all layered over the live preview, which
  /// covered the very product the user was trying to frame.
  bool _showBriefing = true;

  // --- Help (guided only, 2026-10-13) ---------------------------------------
  // Additive guidance help. None of this changes a score, a pass/fail, the
  // auto-capture rule, zoom or selection; the shutter is never disabled.

  /// When the current shot began live checking, for the 20 s help timer.
  DateTime _shotStartedAt = DateTime.now();
  static const Duration helpAfter = Duration(seconds: 20);
  Timer? _helpTimer;

  /// The "still not passing" help card is showing.
  bool _showHelpCard = false;

  /// Once the help card is dismissed or acted on, do not reshow it this shot.
  bool _helpResolvedThisShot = false;

  /// Retakes (an undo of a captured shot) counted per intended role.
  final Map<String, int> _retakes = {};

  /// Roles whose setup card has already shown, so it appears once per role.
  final Set<String> _setupShownRoles = {};
  bool _showSetupCard = false;
  String? _setupCardRole;

  /// Study logging: the hash of the last UNDONE photo per slot, so the next
  /// capture of that slot records retake_of (study mode only).
  final Map<String, String> _undoneHashBySlot = {};

  /// The shot slot name used in the study log: main | angle1 | angle2 | detail
  /// | extra (from the step label).
  String _slotName(ShotStep s) => s.label.toLowerCase().replaceAll(' ', '');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _showBriefing = true; // the same card in both conditions
    _autoCapture = _guided;
    _startCamera();
    // The 20 s "still not passing" help card (guided only).
    if (_guided) {
      _helpTimer =
          Timer.periodic(const Duration(seconds: 1), (_) => _maybeShowHelp());
    }
  }

  /// Resets the per-shot help state when a new shot begins.
  void _resetShotHelp() {
    _shotStartedAt = DateTime.now();
    _helpResolvedThisShot = false;
    _showHelpCard = false;
  }

  /// Shows the help card once a guided shot has not passed for [helpAfter].
  void _maybeShowHelp() {
    if (!mounted || !_guided) return;
    if (_showBriefing || _showSetupCard || _showHelpCard) return;
    if (_scoring || _capturing || _helpResolvedThisShot) return;
    if (_guidance.ready) return; // passing now: nothing to help with
    if (DateTime.now().difference(_shotStartedAt) < helpAfter) return;
    setState(() => _showHelpCard = true);
    StudyLog.log('help_card_shown', {
      'role': _stepAt(_step).intendedRole,
      'seconds': DateTime.now().difference(_shotStartedAt).inSeconds,
    });
  }

  /// The label of the highest-priority failing check, for the help card.
  String? _primaryFailingLabel() {
    final failing = {
      for (final c in _guidance.checks)
        if (c.passed == false) c.name: c
    };
    for (final name in GuidanceResult.instructionOrder) {
      if (failing.containsKey(name)) return failing[name]!.label;
    }
    return failing.isEmpty ? null : failing.values.first.label;
  }

  /// Counts a retake of [role] and, on the 3rd for that role, shows the setup
  /// card once.
  void _registerRetake(String role) {
    final n = (_retakes[role] ?? 0) + 1;
    _retakes[role] = n;
    if (n >= 3 && !_setupShownRoles.contains(role)) {
      _setupShownRoles.add(role);
      setState(() {
        _showSetupCard = true;
        _setupCardRole = role;
      });
      StudyLog.log('setup_check_shown', {'role': role, 'retakes': n});
    }
  }

  /// "Start this product again": keeps every saved photo (nothing deleted), and
  /// in study mode logs a restart event with the time, then returns home.
  Future<void> _startProductAgain() async {
    StudyLog.log('restart',
        {'role': _setupCardRole, 'photos_kept': _captured.length});
    setState(() => _showSetupCard = false);
    try {
      await _controller?.stopImageStream();
    } catch (_) {}
    if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
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
        ResolutionPreset.veryHigh,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.yuv420,
      );
      await controller.initialize();
      if (!mounted) return;
      _controller = controller;

      // Read the exposure compensation range once. Some devices report an empty
      // range (min == max == 0), meaning exposure control is unavailable.
      try {
        _minExposure = await controller.getMinExposureOffset();
        _maxExposure = await controller.getMaxExposureOffset();
        _exposureSupported = _maxExposure > _minExposure;
        _exposureOffset = 0.0;
        await controller.setExposureOffset(0.0);
      } catch (e) {
        _exposureSupported = false;
        debugPrint('Exposure control unavailable on this device. $e');
      }

      // The photo's real resolution limits useful digital zoom (AutoZoom.capFor).
      final ps = controller.value.previewSize;
      if (ps != null) {
        _detailZoomCap = AutoZoom.capFor(math.min(ps.width, ps.height));
        debugPrint('[zoom] capture ${ps.width.toInt()}x${ps.height.toInt()}, '
            'auto zoom up to ${_detailZoomCap.toStringAsFixed(2)}x');
      }

      // Zoom range, read once. A device with no zoom reports min == max.
      try {
        _minZoom = await controller.getMinZoomLevel();
        _maxZoom = (await controller.getMaxZoomLevel())
            .clamp(_minZoom, maxZoomCap)
            .toDouble();
        _zoomSupported = _maxZoom > _minZoom;
        _zoom = _minZoom;
        await controller.setZoomLevel(_zoom);
      } catch (e) {
        _zoomSupported = false;
        debugPrint('Zoom unavailable on this device. $e');
      }

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
    if (!_guided) return; // UNGUIDED: never ask for guidance
    if (_checkInFlight || _scoring || _capturing || _showBriefing) return;
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

    _runGuidanceCheck(image);
  }

  /// Converts the frame and asks the server to check it.
  ///
  /// The conversion runs on the main isolate deliberately. The obvious choice is
  /// compute(), but that spawns a fresh isolate per frame and copies the whole
  /// camera planes across the boundary, which on a modest handset costs far more
  /// than the conversion itself. The device log showed continuous garbage
  /// collection of twenty to thirty megabyte objects and hundreds of skipped
  /// frames. Sampling directly at a small target size is cheap enough to do
  /// inline, so no isolate is needed at all.
  Future<void> _runGuidanceCheck(CameraImage image) async {
    final started = DateTime.now();
    try {
      final payload = FramePayload.fromCameraImage(image);
      final jpeg = FrameConverter.convert(payload);
      final convertMs = DateTime.now().difference(started).inMilliseconds;

      // The camera stream delivers frames in SENSOR orientation (landscape:
      // width > height) while the phone is held upright, so the server is told
      // to upright them with the camera's sensorOrientation rather than
      // rotating in Dart. Log the frame size once to confirm this on device.
      final sensorOrientation = _controller?.description.sensorOrientation ?? 0;
      if (!_loggedFrameDims) {
        _loggedFrameDims = true;
        final landscape = payload.width > payload.height;
        debugPrint(
            '[guidance] decoded frame ${payload.width}x${payload.height} '
            '(${landscape ? "LANDSCAPE / sensor orientation" : "upright"}), '
            'sensorOrientation=$sensorOrientation -> rotation sent');
      }

      final shot = _stepAt(_step).shotType;
      final result =
          await _api.guidance(jpeg, shot: shot, rotation: sensorOrientation);
      final totalMs = DateTime.now().difference(started).inMilliseconds;

      if (_diagnostics) {
        if (result.ok) {
          final g = result.value!;
          final scores = g.checks
              .map((c) => '${c.name}=${c.score.toStringAsFixed(2)}')
              .join(' ');
          debugPrint('[guidance] ok in ${totalMs}ms '
              '(convert ${convertMs}ms, ${jpeg.length ~/ 1024}KB) '
              'ready=${g.ready} $scores');
        } else {
          debugPrint('[guidance] FAILED in ${totalMs}ms. '
              '${result.failure!.kind}. ${result.failure!.technical}');
        }
      }

      _applyGuidance(result, started);
    } catch (e, st) {
      debugPrint('[guidance] threw after '
          '${DateTime.now().difference(started).inMilliseconds}ms. $e');
      debugPrint('$st');
    } finally {
      _watchdog?.cancel();
      _checkInFlight = false;
    }
  }

  void _applyGuidance(ApiResult<GuidanceResult> result, DateTime sentAt) {
    if (!mounted) return;

    if (!result.ok) {
      // A dropped frame keeps the previous reading rather than blanking the
      // indicators, which would make the interface flicker on a weak network.
      _guidanceFailures++;
      if (_guidanceFailures >= failuresBeforeWarning &&
          !_warnedAboutConnection) {
        _warnedAboutConnection = true;
        ErrorView.showSnack(context, result.failure!);
      }
      return;
    }

    _guidanceFailures = 0;
    _warnedAboutConnection = false;
    final g = result.value!;

    // A frame sent before the last zoom change settled shows the old zoom: it
    // updates the lights but counts neither towards auto-capture nor as a
    // reason to zoom again.
    final stale = sentAt.isBefore(_lastZoomChange.add(AutoZoom.settle));
    setState(() {
      _guidance = g;
      _stableFrames = (g.ready && !stale) ? _stableFrames + 1 : 0;
    });

    _maybeApplyExposureHint(g.exposureHint);
    if (!stale) _maybeApplyZoomHint(g.zoomHint);

    if (_autoCapture &&
        _stableFrames >= stableFramesNeeded &&
        !_capturing &&
        _step < _steps.length) {
      _capture(auto: true);
    }
  }

  /// Applies the server's exposure hint (+1 brighten, -1 darken) as camera
  /// exposure compensation, at most one step every [exposureStepInterval] so it
  /// does not oscillate, kept within the device's supported range.
  void _maybeApplyExposureHint(int hint) {
    if (hint == 0 || !_exposureSupported) return;
    final now = DateTime.now();
    if (now.difference(_lastExposureStep) < exposureStepInterval) return;
    final target = (_exposureOffset + hint * exposureStepEv)
        .clamp(_minExposure, _maxExposure)
        .toDouble();
    if ((target - _exposureOffset).abs() < 0.001) {
      return; // already at the limit
    }
    _lastExposureStep = now;
    _setExposure(target);
  }

  /// Applies the server's zoom hint while Auto is on, at most once per
  /// [AutoZoom.minInterval], never while the owner is zooming by hand this shot.
  /// A change restarts the steady-frame count, so a photo is never taken before
  /// focus has settled at the new zoom.
  void _maybeApplyZoomHint(double hint) {
    if (!_autoCapture || !_zoomSupported || _manualZoomThisShot || _capturing) {
      return;
    }
    final now = DateTime.now();
    if (now.difference(_lastAutoZoom) < AutoZoom.minInterval) return;
    final next = AutoZoom.next(
        current: _zoom,
        hint: hint,
        min: _minZoom,
        max: _maxZoom,
        cap: _detailZoomCap);
    if (next == null) return;
    _lastAutoZoom = now;
    _stableFrames = 0;
    _zoomIsAuto = true;
    _setZoom(next);
  }

  /// Sets the camera exposure compensation and updates the on-screen label.
  Future<void> _setExposure(double offset) async {
    final c = _controller;
    if (c == null || !_exposureSupported) return;
    final clamped = offset.clamp(_minExposure, _maxExposure).toDouble();
    try {
      await c.setExposureOffset(clamped);
      if (mounted) setState(() => _exposureOffset = clamped);
    } catch (e) {
      debugPrint('setExposureOffset failed. $e');
    }
  }

  /// Resets exposure to neutral, used when moving to the next shot so each shot
  /// starts from the camera's own metering.
  /// Sets the camera zoom and updates the slider. The preview, the guidance
  /// frames and the photo all use the same zoom, so guidance checks exactly
  /// what will be captured.
  Future<void> _setZoom(double level) async {
    final c = _controller;
    if (c == null || !_zoomSupported) return;
    final clamped = level.clamp(_minZoom, _maxZoom).toDouble();
    _lastZoomChange = DateTime.now();
    try {
      await c.setZoomLevel(clamped);
      if (mounted) setState(() => _zoom = clamped);
    } catch (e) {
      debugPrint('setZoomLevel failed. $e');
    }
  }

  void _resetExposure() {
    if (!_exposureSupported) return;
    _lastExposureStep = DateTime.fromMillisecondsSinceEpoch(0);
    _setExposure(0.0);
  }

  /// Mean brightness (0..255) of a small thumbnail of the captured JPEG, or
  /// null if it cannot be decoded. Used to catch a completely black frame.
  double? _meanBrightness(Uint8List jpeg) {
    try {
      final decoded = img.decodeImage(jpeg);
      if (decoded == null) return null;
      final thumb = img.copyResize(decoded, width: 32);
      var sum = 0.0;
      var n = 0;
      for (final p in thumb) {
        sum += img.getLuminance(p);
        n++;
      }
      return n == 0 ? null : sum / n;
    } catch (e) {
      debugPrint('Brightness check failed. $e');
      return null;
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

      // The camera plugin reconfigures its capture session when the stream
      // stops. Calling takePicture before that completes throws a null session
      // error inside the plugin, which surfaces as a channel error. A short
      // settle plus one retry covers it without a visible delay.
      await Future<void>.delayed(const Duration(milliseconds: 250));

      XFile file;
      try {
        file = await controller.takePicture();
      } on CameraException catch (e) {
        debugPrint('First capture attempt failed (${e.code}). Retrying once.');
        await Future<void>.delayed(const Duration(milliseconds: 400));
        file = await controller.takePicture();
      }

      var bytes = await file.readAsBytes();

      // Black frame guard. A capture sometimes comes back completely black.
      // Never send a black frame for scoring: retry once, then warn and stop.
      final b1 = _meanBrightness(bytes);
      if (b1 != null && b1 < blackFrameThreshold) {
        debugPrint('Captured frame is black (mean $b1). Retrying once.');
        await Future<void>.delayed(const Duration(milliseconds: 300));
        try {
          final retry = await controller.takePicture();
          bytes = await retry.readAsBytes();
        } catch (e) {
          debugPrint('Black-frame retry capture failed. $e');
        }
        final b2 = _meanBrightness(bytes);
        if (b2 != null && b2 < blackFrameThreshold) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                content: Text('The photo came out black. Check nothing is '
                    'covering the camera and try again.')));
          }
          if (mounted) await controller.startImageStream(_onFrame);
          return; // never add a black frame to the set
        }
      }

      if (!mounted) return;

      // Study mode: keep the photo itself, byte-identical to what is hashed and sent,
      // at the moment it is taken, so a photo the participant later undoes is kept too.
      // A no-op outside study mode; never throws.
      unawaited(StudyData.savePhoto(bytes));

      // Study logging: a photo_captured event the moment it is saved (item 1).
      if (StudySession.current != null) {
        final slot = _slotName(_stepAt(_captured.length));
        final meta = StudyLog.imageMeta(bytes);
        final retakeOf = _undoneHashBySlot.remove(slot);
        unawaited(StudyLog.photoCaptured(
          bytes: bytes,
          shotRequested: slot,
          retakeOf: retakeOf,
          source: 'in_app',
          width: meta.width,
          height: meta.height,
          exifOrientation: meta.exif,
        ));
      }

      setState(() {
        _captured.add(bytes);
        _step = _captured.length;
        _confirmation = _guided
            ? ShotPlan.confirmation(_captured.length,
                plan: _steps, required: _required)
            : 'Photo ${_captured.length} taken.';
      });

      // Brief confirmation over the preview, then the next shot's briefing.
      _confirmationTimer?.cancel();
      _confirmationTimer = Timer(const Duration(milliseconds: 1600), () {
        if (!mounted) return;
        setState(() {
          _confirmation = null;
          if (_step < _steps.length) {
            _showBriefing = true; // the same card in both conditions
            _stableFrames = 0;
            _guidance = GuidanceResult.empty();
            _resetShotHelp();
          }
        });
        // Each shot starts from neutral exposure; the next grey background will
        // raise it again on its own.
        _resetExposure();
        // Each shot also starts unzoomed, so a zoomed detail shot does not
        // carry over into the next view; auto zoom is free to act again.
        _manualZoomThisShot = false;
        _zoomIsAuto = false;
        _setZoom(_minZoom);
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
    if (widget.returnPhotos) {
      // The missing shots: the results screen checks them together with the
      // photos that already passed.
      if (_captured.isEmpty) return;
      try {
        await _controller?.stopImageStream();
      } catch (_) {}
      if (mounted) Navigator.of(context).pop(List<Uint8List>.of(_captured));
      return;
    }
    if (_captured.length < 2) return;

    // Study mode: the participant picks their own set BEFORE any result is
    // shown (v1.1.0). Leaving the picks screen returns to the camera.
    final study = StudySession.current;
    if (study != null && !_picksDone) {
      try {
        await _controller?.stopImageStream();
      } catch (_) {}
      study.captureEndAt = DateTime.now().toUtc();
      StudyLog.log('capture_end',
          {'photo_hashes': _captured.map(StudyLog.photoHash).toList()});
      if (!mounted) return;
      final picks = await Navigator.of(context).push<Map<String, Uint8List>>(
          MaterialPageRoute(builder: (_) => OwnPicksScreen(photos: _captured)));
      if (!mounted) return;
      if (picks == null) {
        try {
          await _controller?.startImageStream(_onFrame);
        } catch (_) {}
        return;
      }
      _picksDone = true;
      StudyLog.ownPicks(picks);
    }

    setState(() => _scoring = true);

    try {
      await _controller?.stopImageStream();
    } catch (_) {}

    final result = await _api.batch(_captured);
    if (!mounted) return;
    if (result.ok && study != null) {
      StudyLog.batchResult(_captured, result.value!);
    }

    if (!result.ok) {
      setState(() => _scoring = false);
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
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
        draft: widget.draft,
        result: result.value!,
        images: List<Uint8List>.of(_captured),
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
    // An undo is the user's intent to retake this role; counted for the setup
    // card. The role of the photo being removed is the step at its index.
    final step = _stepAt(_captured.length - 1);
    final role = step.intendedRole;
    // Remember the undone photo's hash so the next capture of this slot records
    // retake_of (study mode only).
    if (StudySession.current != null) {
      _undoneHashBySlot[_slotName(step)] = StudyLog.photoHash(_captured.last);
    }
    setState(() {
      _captured.removeLast();
      _step = _captured.length;
      _confirmation = null;
    });
    if (_guided) _registerRetake(role);
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
    _helpTimer?.cancel();
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
    final step = _stepAt(_step);
    final canFinish = done >= _required;

    return PopScope(
      // Only guard back when there are photos to lose; an empty session leaves
      // freely so the gesture is not needlessly blocked.
      canPop: _captured.isEmpty,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final leave = await confirmLeave(
          context,
          title: 'Leave the camera?',
          message: 'You have taken ${_captured.length} '
              'photo${_captured.length == 1 ? '' : 's'}. '
              'They will be discarded if you leave now.',
        );
        if (leave && context.mounted) {
          try {
            await _controller?.stopImageStream();
          } catch (_) {}
          if (context.mounted) Navigator.of(context).pop();
        }
      },
      child: Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          CameraPreview(controller),
          ScoredRegionGuide(
            guidance: _guidance,
            waiting: _checkInFlight,
            shotType: step.shotType,
            neutral: !_guided,
            // Guided only: outline the detected product box over the preview.
            productBox: _guided ? _guidance.productBox : null,
          ),
          SafeArea(
            child: Column(
              children: [
                _TopBar(
                  productName: widget.draft.name,
                  autoCapture: _autoCapture,
                  // No auto-capture in the UNGUIDED condition: it needs guidance.
                  onToggleAuto: _guided
                      ? () => setState(() => _autoCapture = !_autoCapture)
                      : null,
                  onHelp: () => showHelpSheet(context, HelpTopic.capture),
                ),
                const SizedBox(height: 8),
                if (_guided)
                  _ShotProgress(steps: _steps, captured: done)
                else
                  _ShotReminder(label: '', count: done),
                const Spacer(),
                // A short reminder only. The full explanation was given on the
                // briefing screen, so nothing large sits over the frame guide.
                if (_confirmation != null)
                  _Confirmation(text: _confirmation!)
                else if (_guided)
                  _ShotReminder(label: step.label),
                const SizedBox(height: 12),
                if (_guided)
                  GuidanceOverlay(
                    guidance: _guidance,
                    waitingForServer: _checkInFlight,
                  ),
                if (_exposureSupported) ...[
                  const SizedBox(height: 10),
                  _BrightnessControl(
                    offset: _exposureOffset,
                    min: _minExposure,
                    max: _maxExposure,
                    onChanged: (v) {
                      // Pause the automatic stepping while the user adjusts.
                      _lastExposureStep = DateTime.now();
                      _setExposure(v);
                    },
                  ),
                ],
                if (_zoomSupported) ...[
                  const SizedBox(height: 8),
                  _ZoomControl(
                    zoom: _zoom,
                    min: _minZoom,
                    max: _maxZoom,
                    auto: _zoomIsAuto,
                    soft: _zoom > _detailZoomCap + 0.01,
                    onChanged: (v) {
                      // The owner takes over the zoom for this shot.
                      _manualZoomThisShot = true;
                      _zoomIsAuto = false;
                      _setZoom(v);
                    },
                  ),
                ],
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
          // Briefing sits above everything. The camera stays alive behind it so
          // there is no delay when the user taps ready.
          if (_showBriefing)
            ShotCard(
              guided: _guided,
              step: step,
              shotNumber: _step + 1,
              total: _steps.length,
              optional: _step >= _required,
              canFinishInstead: canFinish,
              onReady: () => setState(() {
                _showBriefing = false;
                _stableFrames = 0;
                _resetShotHelp();
              }),
              onFinish: _finish,
            ),

          // Guided help cards (2026-10-13). Dismissible; the shutter stays live.
          if (_showHelpCard && _guided)
            _HelpCard(
              checkLabel: _primaryFailingLabel(),
              fix: _guidance.primaryInstruction ??
                  'Adjust the shot and try again.',
              onTakeAnyway: () {
                setState(() {
                  _showHelpCard = false;
                  _helpResolvedThisShot = true;
                });
                _capture();
              },
              onDismiss: () => setState(() {
                _showHelpCard = false;
                _helpResolvedThisShot = true;
              }),
            ),
          if (_showSetupCard && _guided)
            _SetupCard(
              onContinue: () => setState(() => _showSetupCard = false),
              onStartAgain: _startProductAgain,
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
    ),
    );
  }
}

/// Manual brightness (exposure compensation) slider, shown near the indicators.
/// Photographers teach exactly this "slide the brightness up" step, so it is
/// visible whenever the device supports exposure control. The same offset the
/// automatic hint adjusts.
class _BrightnessControl extends StatelessWidget {
  final double offset;
  final double min;
  final double max;
  final ValueChanged<double> onChanged;

  const _BrightnessControl({
    required this.offset,
    required this.min,
    required this.max,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final label = offset >= 0
        ? '+${offset.toStringAsFixed(1)}'
        : offset.toStringAsFixed(1);
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 24),
      padding: const EdgeInsets.only(left: 14, right: 6),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Row(
        children: [
          const Icon(Icons.wb_sunny_outlined, color: Colors.white, size: 18),
          const SizedBox(width: 6),
          SizedBox(
            width: 104,
            child: Text('Brightness $label',
                style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600)),
          ),
          Expanded(
            child: Slider(
              value: offset.clamp(min, max),
              min: min,
              max: max,
              onChanged: onChanged,
            ),
          ),
        ],
      ),
    );
  }
}

/// Zoom slider, styled like the brightness control.
class _ZoomControl extends StatelessWidget {
  final double zoom;
  final double min;
  final double max;

  /// The zoom was set by auto zoom; the label says so.
  final bool auto;

  /// Zoomed past what the camera's resolution supports: the label turns amber,
  /// because the photo will come out soft. Moving closer keeps the detail.
  final bool soft;
  final ValueChanged<double> onChanged;

  const _ZoomControl({
    required this.zoom,
    required this.min,
    required this.max,
    this.auto = false,
    this.soft = false,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 24),
      padding: const EdgeInsets.only(left: 14, right: 6),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Row(
        children: [
          const Icon(Icons.zoom_in, color: Colors.white, size: 18),
          const SizedBox(width: 6),
          SizedBox(
            width: 116,
            child: Text(
                '${auto ? 'Auto zoom' : 'Zoom'} ${zoom.toStringAsFixed(1)}x',
                style: TextStyle(
                    color: soft ? Colors.amber.shade300 : Colors.white,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600)),
          ),
          Expanded(
            child: Slider(
              value: zoom.clamp(min, max),
              min: min,
              max: max,
              onChanged: onChanged,
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
  final VoidCallback? onToggleAuto;
  final VoidCallback onHelp;

  const _TopBar({
    required this.productName,
    required this.autoCapture,
    required this.onToggleAuto,
    required this.onHelp,
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
        // 48 dp tap area and a spoken label (accessibility pass, v1.1.0).
        if (onToggleAuto != null)
          Semantics(
            button: true,
            label: autoCapture
                ? 'Auto capture on. Tap for manual'
                : 'Manual capture. Tap for auto',
            excludeSemantics: true,
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: onToggleAuto,
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Center(
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.55),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(
                          autoCapture
                              ? Icons.motion_photos_auto
                              : Icons.touch_app,
                          color: Colors.white,
                          size: 16),
                      const SizedBox(width: 6),
                      Text(autoCapture ? 'Auto' : 'Manual',
                          style: const TextStyle(
                              color: Colors.white, fontSize: 12.5)),
                    ]),
                  ),
                ),
              ),
            ),
          ),
        const SizedBox(width: 4),
        Semantics(
          button: true,
          label: 'Help',
          excludeSemantics: true,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: onHelp,
            child: SizedBox(
              width: 48,
              height: 48,
              child: Center(
                child: Container(
                  padding: const EdgeInsets.all(7),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.55),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(Icons.help_outline,
                      color: Colors.white, size: 18),
                ),
              ),
            ),
          ),
        ),
      ]),
    );
  }
}

/// Progress strip showing which shots are done and which remain.
class _ShotProgress extends StatelessWidget {
  final List<ShotStep> steps;
  final int captured;

  const _ShotProgress({required this.steps, required this.captured});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(steps.length, (i) {
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
              steps[i].label,
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

/// A slim reminder of which shot is being taken.
///
/// The full explanation lives on the briefing screen, so this stays small and
/// out of the way of the frame guide.
class _ShotReminder extends StatelessWidget {
  final String label;

  /// Unguided study condition: show only how many photos were taken.
  final int? count;

  const _ShotReminder({required this.label, this.count});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.black.withOpacity(0.5),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Text(
        count != null
            ? '$count photo${count == 1 ? '' : 's'}'
            : 'Taking the ${label.toLowerCase()} shot',
        style: const TextStyle(
            color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500),
      ),
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
    return Semantics(
      button: true,
      label: 'Take photo',
      excludeSemantics: true,
      child: GestureDetector(
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
      ),
    );
  }
}

/// Shown when a guided shot has not passed for 20 seconds. Names the main
/// failing check, gives one plain fix, and lets the user take the photo anyway.
/// The shutter is never disabled; this is help, not a block.
class _HelpCard extends StatelessWidget {
  final String? checkLabel;
  final String fix;
  final VoidCallback onTakeAnyway;
  final VoidCallback onDismiss;

  const _HelpCard({
    required this.checkLabel,
    required this.fix,
    required this.onTakeAnyway,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    return Positioned(
      left: 20,
      right: 20,
      bottom: 150,
      child: Material(
        color: Colors.transparent,
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
          decoration: BoxDecoration(
            color: const Color(0xFF12161C).withValues(alpha: 0.96),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Colors.white24),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Icon(Icons.lightbulb_outline,
                    color: Colors.amber.shade300, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    checkLabel == null
                        ? 'Still working on this shot'
                        : 'Still working on: $checkLabel',
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 15.5,
                        fontWeight: FontWeight.w700),
                  ),
                ),
                Semantics(
                  button: true,
                  label: 'Dismiss',
                  excludeSemantics: true,
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: onDismiss,
                    child: const SizedBox(
                      width: 40,
                      height: 40,
                      child: Icon(Icons.close, color: Colors.white70, size: 20),
                    ),
                  ),
                ),
              ]),
              const SizedBox(height: 6),
              Text(fix,
                  style: const TextStyle(
                      color: Colors.white, fontSize: 14.5, height: 1.35)),
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton(
                  onPressed: onTakeAnyway,
                  child: const Text('Take it anyway'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Shown after the 3rd retake of the same shot role: a short setup checklist
/// and a choice to continue or start this product again (nothing is deleted).
class _SetupCard extends StatelessWidget {
  final VoidCallback onContinue;
  final VoidCallback onStartAgain;

  const _SetupCard({required this.onContinue, required this.onStartAgain});

  static const _items = <(IconData, String)>[
    (Icons.wb_incandescent_outlined, 'Lamp on, or near a bright window'),
    (Icons.stay_current_portrait_outlined, 'Phone steady on the stand'),
    (Icons.auto_awesome_outlined, 'Lens wiped clean'),
    (Icons.center_focus_strong_outlined,
        'Product in the middle of the white box'),
  ];

  @override
  Widget build(BuildContext context) {
    return Positioned.fill(
      child: Material(
        color: const Color(0xFF12161C).withValues(alpha: 0.96),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(26, 24, 26, 26),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text("Let's check your setup",
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 24,
                        fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                const Text(
                    'A few retakes usually means the setup needs a small fix. '
                    'Check these, then carry on.',
                    style: TextStyle(color: Colors.white70, fontSize: 15, height: 1.4)),
                const SizedBox(height: 22),
                for (final (icon, text) in _items)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Row(children: [
                      Icon(icon, color: Colors.amber.shade300, size: 24),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Text(text,
                            style: const TextStyle(
                                color: Colors.white, fontSize: 16, height: 1.35)),
                      ),
                    ]),
                  ),
                const Spacer(),
                FilledButton(
                  style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(52)),
                  onPressed: onContinue,
                  child: const Text('Check setup and continue'),
                ),
                const SizedBox(height: 8),
                TextButton(
                  onPressed: onStartAgain,
                  child: Text('Start this product again',
                      style: TextStyle(color: Colors.white.withValues(alpha: 0.85))),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

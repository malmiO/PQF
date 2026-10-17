import 'package:flutter/material.dart';

/// Asks the user to confirm leaving a screen where going back loses work
/// (capture in progress, results, a video being made). Returns true to leave.
///
/// Used with PopScope so the predictive-back gesture (default on targetSdk 36)
/// does not silently discard a capture session or an in-flight video.
Future<bool> confirmLeave(
  BuildContext context, {
  required String title,
  required String message,
  String leaveLabel = 'Leave',
  String stayLabel = 'Stay',
}) async {
  final leave = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(stayLabel)),
        FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(leaveLabel)),
      ],
    ),
  );
  return leave ?? false;
}

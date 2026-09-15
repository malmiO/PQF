import 'package:flutter/material.dart';
import '../models/api_result.dart';

/// Displays a failure in terms the user can act on.
///
/// The technical detail is deliberately not shown. It goes to the debug console
/// where it helps the developer, while the user sees what happened and what to
/// do about it.
class ErrorView extends StatelessWidget {
  final ApiFailure failure;
  final VoidCallback? onRetry;
  final VoidCallback? onDismiss;

  const ErrorView({
    super.key,
    required this.failure,
    this.onRetry,
    this.onDismiss,
  });

  IconData get _icon {
    switch (failure.kind) {
      case FailureKind.unreachable:
        return Icons.wifi_off;
      case FailureKind.timeout:
        return Icons.hourglass_empty;
      case FailureKind.quotaExceeded:
        return Icons.hourglass_disabled;
      case FailureKind.badImage:
        return Icons.image_not_supported_outlined;
      default:
        return Icons.error_outline;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFDECEA),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFC62828), width: 1.2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(_icon, color: const Color(0xFFC62828), size: 21),
            const SizedBox(width: 10),
            Expanded(
              child: Text(failure.message,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w600, height: 1.3)),
            ),
          ]),
          if (failure.action != null) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.only(left: 31),
              child: Text(failure.action!,
                  style: const TextStyle(fontSize: 13.5, height: 1.4)),
            ),
          ],
          if (onRetry != null || onDismiss != null) ...[
            const SizedBox(height: 6),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (onDismiss != null)
                  TextButton(onPressed: onDismiss, child: const Text('Close')),
                if (onRetry != null && failure.retryable)
                  FilledButton(onPressed: onRetry, child: const Text('Try again')),
              ],
            ),
          ],
        ],
      ),
    );
  }

  /// Convenience for transient failures during capture, where a full panel
  /// would obscure the viewfinder.
  static void showSnack(BuildContext context, ApiFailure failure) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(failure.action == null
            ? failure.message
            : '${failure.message} ${failure.action}'),
        duration: const Duration(seconds: 5),
        behavior: SnackBarBehavior.floating,
      ));
  }
}

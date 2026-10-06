/// An evaluation session (v1.1.0, Step 7). Only codes are kept: a participant
/// code (P01...), the condition and a product code. Never a name or contact.
class StudySession {
  static const guided = 'GUIDED';
  static const unguided = 'UNGUIDED';

  final String participant;
  final String product;

  /// 1 or 2: which of the participant's two sessions this is.
  final int session;
  final DateTime startedAt;
  DateTime? captureEndAt;
  DateTime? videoReadyAt;

  StudySession({
    required this.participant,
    required this.product,
    required this.session,
    DateTime? startedAt,
  }) : startedAt = startedAt ?? DateTime.now().toUtc();

  /// The session running now, or null outside study mode.
  static StudySession? current;

  /// GUIDED or UNGUIDED, from the counterbalanced order.
  String get condition => abbaOrder(participant)[session - 1];

  static final RegExp participantPattern = RegExp(r'^P\d{2,3}$');
  static final RegExp productPattern = RegExp(r'^[A-Za-z0-9_-]{1,16}$');

  /// ABBA over participants (A = UNGUIDED, B = GUIDED): P01 AB, P02 BA, P03 BA,
  /// P04 AB, then repeating. The server's export uses the same rule.
  static List<String> abbaOrder(String participant) {
    final n = int.tryParse(participant.replaceAll(RegExp(r'\D'), '')) ?? 1;
    const ab = [unguided, guided];
    return const {0, 3}.contains((n - 1) % 4) ? ab : ab.reversed.toList();
  }
}

/// Whether the camera may ask the server for live guidance. In the UNGUIDED
/// condition it never does: no /guidance call, no overlay, no auto-capture.
class GuidancePolicy {
  static bool guided(StudySession? s) =>
      s == null || s.condition == StudySession.guided;
}

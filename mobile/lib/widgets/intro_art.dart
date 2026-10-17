import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Vector illustrations for the first-run introduction (v1.5.0). Drawn with
/// CustomPaint, so there are no photos and no image assets.
enum IntroArt { whatIs, howItWorks, bestSetup }

class IntroIllustration extends StatelessWidget {
  final IntroArt art;
  final double size;
  const IntroIllustration({super.key, required this.art, this.size = 240});

  @override
  Widget build(BuildContext context) {
    final p = Theme.of(context).colorScheme.primary;
    final CustomPainter painter = switch (art) {
      IntroArt.whatIs => _WhatIsPainter(p),
      IntroArt.howItWorks => _HowPainter(p),
      IntroArt.bestSetup => _SetupPainter(p),
    };
    return Semantics(
      excludeSemantics: true,
      child: SizedBox(width: size, height: size, child: CustomPaint(painter: painter)),
    );
  }
}

const _gold = Color(0xFFE0A526);
const _soft = Color(0xFFE8EDF6);

Paint _fill(Color c) => Paint()..color = c;
Paint _line(Color c, double w) => Paint()
  ..color = c
  ..style = PaintingStyle.stroke
  ..strokeWidth = w
  ..strokeCap = StrokeCap.round
  ..strokeJoin = StrokeJoin.round;

void _phone(Canvas c, Rect r, Color body) {
  c.drawRRect(RRect.fromRectAndRadius(r, Radius.circular(r.width * .14)), _fill(body));
  c.drawRRect(
      RRect.fromRectAndRadius(r.deflate(r.width * .07), Radius.circular(r.width * .09)),
      _fill(Colors.white));
}

void _sparkle(Canvas c, Offset o, double s, Color col) {
  final p = Path()
    ..moveTo(o.dx, o.dy - s)
    ..quadraticBezierTo(o.dx, o.dy, o.dx + s, o.dy)
    ..quadraticBezierTo(o.dx, o.dy, o.dx, o.dy + s)
    ..quadraticBezierTo(o.dx, o.dy, o.dx - s, o.dy)
    ..quadraticBezierTo(o.dx, o.dy, o.dx, o.dy - s);
  c.drawPath(p, _fill(col));
}

void _play(Canvas c, Offset o, double s, Color col) {
  c.drawPath(
      Path()
        ..moveTo(o.dx - s * .6, o.dy - s)
        ..lineTo(o.dx + s, o.dy)
        ..lineTo(o.dx - s * .6, o.dy + s)
        ..close(),
      _fill(col));
}

class _WhatIsPainter extends CustomPainter {
  final Color p;
  _WhatIsPainter(this.p);
  @override
  void paint(Canvas c, Size s) {
    final w = s.width;
    c.drawCircle(Offset(w / 2, w / 2), w * .46, _fill(_soft));
    // Phone with a product photo (a ring) and a certified tick.
    final ph = Rect.fromCenter(center: Offset(w * .40, w * .52), width: w * .34, height: w * .62);
    _phone(c, ph, p);
    final cx = ph.center.dx, cy = ph.center.dy - w * .02;
    c.drawCircle(Offset(cx, cy), w * .07, _line(_gold, w * .018));
    c.drawPath(
        Path()
          ..moveTo(cx - w * .035, cy - w * .075)
          ..lineTo(cx + w * .035, cy - w * .075)
          ..lineTo(cx + w * .055, cy - w * .105)
          ..lineTo(cx - w * .055, cy - w * .105)
          ..close(),
        _fill(p));
    c.drawRRect(
        RRect.fromRectAndRadius(
            Rect.fromLTWH(ph.left + w * .06, ph.bottom - w * .17, w * .22, w * .03),
            Radius.circular(w * .015)),
        _fill(_soft));
    // Certified badge.
    final b = Offset(ph.right - w * .01, ph.top + w * .06);
    c.drawCircle(b, w * .07, _fill(const Color(0xFF2E7D32)));
    c.drawPath(
        Path()
          ..moveTo(b.dx - w * .03, b.dy)
          ..lineTo(b.dx - w * .006, b.dy + w * .026)
          ..lineTo(b.dx + w * .035, b.dy - w * .025),
        _line(Colors.white, w * .018));
    // Video card.
    final v = Rect.fromCenter(center: Offset(w * .72, w * .62), width: w * .30, height: w * .46);
    c.drawRRect(RRect.fromRectAndRadius(v, Radius.circular(w * .04)), _fill(Colors.white));
    c.drawRRect(RRect.fromRectAndRadius(v, Radius.circular(w * .04)), _line(p, w * .012));
    c.drawRRect(RRect.fromRectAndRadius(v.deflate(w * .025), Radius.circular(w * .025)),
        _fill(p.withValues(alpha: .12)));
    c.drawCircle(v.center, w * .06, _fill(p));
    _play(c, v.center.translate(w * .006, 0), w * .03, Colors.white);
    _sparkle(c, Offset(w * .2, w * .2), w * .05, _gold);
    _sparkle(c, Offset(w * .8, w * .26), w * .035, _gold);
  }

  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
}

class _HowPainter extends CustomPainter {
  final Color p;
  _HowPainter(this.p);
  @override
  void paint(Canvas c, Size s) {
    final w = s.width;
    c.drawCircle(Offset(w / 2, w / 2), w * .46, _fill(_soft));
    // Four steps down a path: camera, check, best set, video.
    final pts = [
      Offset(w * .26, w * .24),
      Offset(w * .72, w * .38),
      Offset(w * .28, w * .60),
      Offset(w * .72, w * .78),
    ];
    final path = Path()..moveTo(pts[0].dx, pts[0].dy);
    for (var i = 1; i < pts.length; i++) {
      path.quadraticBezierTo(w / 2, (pts[i - 1].dy + pts[i].dy) / 2, pts[i].dx, pts[i].dy);
    }
    c.drawPath(path, _line(p.withValues(alpha: .35), w * .012));
    for (var i = 0; i < 4; i++) {
      final o = pts[i];
      c.drawCircle(o, w * .11, _fill(i == 3 ? _gold : p));
      switch (i) {
        case 0:
          c.drawRRect(
              RRect.fromRectAndRadius(
                  Rect.fromCenter(center: o, width: w * .11, height: w * .08),
                  Radius.circular(w * .015)),
              _line(Colors.white, w * .012));
          c.drawCircle(o, w * .022, _line(Colors.white, w * .012));
        case 1:
          c.drawPath(
              Path()
                ..moveTo(o.dx - w * .04, o.dy)
                ..lineTo(o.dx - w * .01, o.dy + w * .035)
                ..lineTo(o.dx + w * .045, o.dy - w * .035),
              _line(Colors.white, w * .018));
        case 2:
          for (var k = 0; k < 3; k++) {
            c.drawRRect(
                RRect.fromRectAndRadius(
                    Rect.fromLTWH(o.dx - w * .06 + k * w * .043, o.dy - w * .035, w * .036, w * .07),
                    Radius.circular(w * .008)),
                _fill(Colors.white));
          }
        default:
          _play(c, o.translate(w * .004, 0), w * .035, Colors.white);
      }
      final tp = TextPainter(
        text: TextSpan(
            text: '${i + 1}',
            style: TextStyle(color: p, fontSize: w * .06, fontWeight: FontWeight.bold)),
        textDirection: TextDirection.ltr,
      )..layout();
      final side = i.isEven ? 1 : -1;
      tp.paint(c, o.translate(side * w * .17 - tp.width / 2, -tp.height / 2));
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
}

class _SetupPainter extends CustomPainter {
  final Color p;
  _SetupPainter(this.p);
  @override
  void paint(Canvas c, Size s) {
    final w = s.width;
    c.drawCircle(Offset(w / 2, w / 2), w * .46, _fill(_soft));
    // Light box with a product on a white floor.
    final box = Rect.fromLTWH(w * .50, w * .38, w * .36, w * .34);
    c.drawRRect(RRect.fromRectAndRadius(box, Radius.circular(w * .02)), _fill(Colors.white));
    c.drawRRect(RRect.fromRectAndRadius(box, Radius.circular(w * .02)), _line(p, w * .014));
    c.drawCircle(Offset(box.center.dx, box.top + box.height * .6), w * .045,
        _fill(const Color(0xFFD64545)));
    c.drawRect(
        Rect.fromLTWH(box.center.dx - w * .012, box.top + box.height * .25, w * .024, w * .05),
        _fill(const Color(0xFF9AA3B2)));
    // Light above the box.
    final lamp = Offset(box.center.dx, w * .2);
    for (var i = 0; i < 5; i++) {
      final a = math.pi * (.2 + .15 * i);
      c.drawLine(lamp.translate(math.cos(a) * w * .06, math.sin(a) * w * .06),
          lamp.translate(math.cos(a) * w * .12, math.sin(a) * w * .12), _line(_gold, w * .014));
    }
    c.drawCircle(lamp, w * .04, _fill(_gold));
    // Phone on a tripod, steady, facing the box.
    final hx = w * .23, top = w * .36;
    _phone(c, Rect.fromCenter(center: Offset(hx, top + w * .1), width: w * .14, height: w * .24), p);
    final base = Offset(hx, w * .78);
    c.drawLine(Offset(hx, top + w * .22), base, _line(p, w * .018));
    c.drawLine(base, base.translate(-w * .10, w * .06), _line(p, w * .018));
    c.drawLine(base, base.translate(w * .10, w * .06), _line(p, w * .018));
    c.drawLine(base, base.translate(0, w * .07), _line(p, w * .018));
    for (var x = hx + w * .09; x < box.left - w * .02; x += w * .04) {
      c.drawCircle(Offset(x, top + w * .1), w * .006, _fill(p.withValues(alpha: .5)));
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
}

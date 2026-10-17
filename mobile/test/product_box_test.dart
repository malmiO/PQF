import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/services/pqf_api.dart';

void main() {
  Map<String, dynamic> base() => {
        'ready': true,
        'checks': <dynamic>[],
        'feedback': <dynamic>[],
        'elapsed_ms': 10,
      };

  test('product_box parses to four doubles', () {
    final g = GuidanceResult.fromJson({
      ...base(),
      'product_box': [0.1, 0.2, 0.3, 0.4],
    });
    expect(g.productBox, [0.1, 0.2, 0.3, 0.4]);
  });

  test('missing product_box is null (additive, backward compatible)', () {
    expect(GuidanceResult.fromJson(base()).productBox, isNull);
  });

  test('null product_box is tolerated', () {
    final g = GuidanceResult.fromJson({...base(), 'product_box': null});
    expect(g.productBox, isNull);
  });
}

import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

/// One saved answer to an application question the cloud worker could not
/// answer on its own (e.g. "Do you have a valid UAE driving licence?").
class SavedQA {
  final String question;
  final String answer;
  const SavedQA(this.question, this.answer);

  Map<String, String> toJson() => {'q': question, 'a': answer};

  static SavedQA? fromJson(dynamic j) {
    if (j is! Map) return null;
    final q = (j['q'] ?? '').toString().trim();
    final a = (j['a'] ?? '').toString().trim();
    if (q.isEmpty || a.isEmpty) return null;
    return SavedQA(q, a);
  }
}

/// Answers reused on every Easy Apply form, stored on this phone only
/// (SharedPreferences). They are sent to the cloud worker inside each apply
/// request as `answers.bank` and `answers.custom`.
class ApplyAnswersStore {
  static const _bankKey = 'apply_answer_bank';
  static const _customKey = 'apply_answer_custom';

  /// Common questions shown on the Saved Answers screen.
  /// Keys must match the `bank` keys in cloud/apply_answers.py.
  static const commonFields = <String, String>{
    'phone': 'Phone number',
    'linkedin_url': 'LinkedIn profile URL',
    'nationality': 'Nationality',
    'visa_status': 'Visa / residency status',
    'notice_period': 'Notice period',
    'current_salary': 'Current salary',
    'expected_salary': 'Expected salary',
    'relocate': 'Willing to relocate (Yes / No)',
    'driving_license': 'Driving licence (Yes / No)',
    'english_level': 'English level (e.g. Professional, Native)',
    'arabic_level': 'Arabic level (e.g. Native, Conversational)',
    'degree': 'Highest degree (e.g. Bachelor\'s)',
    'portfolio_url': 'Website / portfolio / GitHub',
  };

  static Future<Map<String, String>> loadBank() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_bankKey);
    if (raw == null || raw.isEmpty) return {};
    try {
      final map = jsonDecode(raw) as Map<String, dynamic>;
      return map.map((k, v) => MapEntry(k, (v ?? '').toString()));
    } catch (_) {
      return {};
    }
  }

  static Future<void> saveBank(Map<String, String> bank) async {
    final prefs = await SharedPreferences.getInstance();
    final clean = <String, String>{};
    bank.forEach((k, v) {
      if (v.trim().isNotEmpty) clean[k] = v.trim();
    });
    await prefs.setString(_bankKey, jsonEncode(clean));
  }

  static Future<List<SavedQA>> loadCustom() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_customKey);
    if (raw == null || raw.isEmpty) return [];
    try {
      return (jsonDecode(raw) as List<dynamic>)
          .map(SavedQA.fromJson)
          .whereType<SavedQA>()
          .toList();
    } catch (_) {
      return [];
    }
  }

  static Future<void> saveCustom(List<SavedQA> items) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
        _customKey, jsonEncode(items.map((e) => e.toJson()).toList()));
  }

  /// Adds or replaces answers (matched by question text, case-insensitive).
  static Future<void> upsertCustom(List<SavedQA> newItems) async {
    final items = await loadCustom();
    for (final n in newItems) {
      items.removeWhere(
          (e) => e.question.toLowerCase() == n.question.toLowerCase());
      items.add(n);
    }
    await saveCustom(items);
  }
}

import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config.dart';
import '../models/job.dart';
import '../models/app_settings.dart';

class SupabaseService {
  static const _base = '${Config.supabaseUrl}/rest/v1';

  static Map<String, String> get _headers => {
        'apikey': Config.supabaseKey,
        'Authorization': 'Bearer ${Config.supabaseKey}',
        'Content-Type': 'application/json',
      };

  // ── Jobs ──────────────────────────────────────────────────────────────────

  static Future<List<Job>> listJobs({String? status, int limit = 100}) async {
    var query = '$_base/jobs?order=date_collected.desc&limit=$limit';
    if (status != null && status != 'all') {
      query += '&status=eq.$status';
    }
    final res = await http.get(Uri.parse(query), headers: _headers);
    if (res.statusCode != 200) return [];
    final list = jsonDecode(res.body) as List<dynamic>;
    return list.map((e) => Job.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> updateJobStatus(String url, String newStatus) async {
    final encoded = Uri.encodeComponent(url);
    await http.patch(
      Uri.parse('$_base/jobs?url=eq.$encoded'),
      headers: {..._headers, 'Prefer': 'return=minimal'},
      body: jsonEncode({'status': newStatus}),
    );
  }

  static Future<Map<String, int>> getJobCounts() async {
    const statuses = ['new', 'applied', 'saved', 'dismissed'];
    final counts = await Future.wait(statuses.map((s) async {
      try {
        final res = await http.get(
          Uri.parse('$_base/jobs?status=eq.$s&select=job_id'),
          headers: {
            ..._headers,
            'Prefer': 'count=exact',
            'Range-Unit': 'items',
            'Range': '0-0',
          },
        );
        final range = res.headers['content-range'] ?? '';
        final parts = range.split('/');
        return int.tryParse(parts.length == 2 ? parts[1] : '0') ?? 0;
      } catch (_) {
        return 0;
      }
    }));
    return Map.fromIterables(statuses, counts);
  }

  // ── Settings (stored in bot_state as setting_* keys) ─────────────────────

  static Future<AppSettings> getSettings() async {
    try {
      final res = await http.get(
        Uri.parse('$_base/bot_state?key=like.setting_%25&select=key,value'),
        headers: _headers,
      );
      if (res.statusCode != 200) return AppSettings.defaults();
      final rows = jsonDecode(res.body) as List<dynamic>;
      final map = <String, String>{
        for (final r in rows)
          (r['key'] as String).replaceFirst('setting_', ''):
              r['value'] as String,
      };
      return AppSettings.fromMap(map);
    } catch (_) {
      return AppSettings.defaults();
    }
  }

  static Future<bool> saveSettings(AppSettings s) async {
    try {
      final entries = s.toMap().entries.toList();
      final body = jsonEncode(entries
          .map((e) => {'key': 'setting_${e.key}', 'value': e.value})
          .toList());
      final res = await http.post(
        Uri.parse('$_base/bot_state'),
        headers: {
          ..._headers,
          'Prefer': 'resolution=merge-duplicates,return=minimal',
        },
        body: body,
      );
      return res.statusCode == 200 || res.statusCode == 201;
    } catch (_) {
      return false;
    }
  }
}

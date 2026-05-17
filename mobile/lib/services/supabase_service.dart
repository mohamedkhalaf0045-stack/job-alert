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

  // Phase 2/3/5: explicit column list so the new fields actually arrive.
  // Without an explicit select, PostgREST returns the default projection which
  // may not include columns added after the table was first introspected.
  static const _jobColumns =
      'job_id,title,company,location,url,source,status,'
      'date_posted,date_collected,llm_score,llm_summary,'
      'skills_match,experience_match,location_match,seniority_match,'
      'matched_skills,missing_skills,red_flags,'
      'duplicate_of_url,cover_letter_draft';

  static Future<List<Job>> listJobs({String? status, int limit = 200,
                                      bool hideDuplicates = true}) async {
    var query = '$_base/jobs?select=$_jobColumns&order=date_collected.desc&limit=$limit';
    if (status != null && status != 'all') {
      query += '&status=eq.$status';
    }
    if (hideDuplicates) {
      query += '&duplicate_of_url=is.null';
    }
    final res = await http.get(Uri.parse(query), headers: _headers);
    if (res.statusCode != 200) return [];
    final list = jsonDecode(res.body) as List<dynamic>;
    return list.map((e) => Job.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Scored jobs only, sorted best score first.
  static Future<List<Job>> listScoredJobs({int limit = 200,
                                            bool hideDuplicates = true}) async {
    var query = '$_base/jobs?select=$_jobColumns'
        '&llm_score=not.is.null'
        '&order=llm_score.desc,date_collected.desc'
        '&limit=$limit';
    if (hideDuplicates) {
      query += '&duplicate_of_url=is.null';
    }
    final res = await http.get(Uri.parse(query), headers: _headers);
    if (res.statusCode != 200) return [];
    final list = jsonDecode(res.body) as List<dynamic>;
    return list.map((e) => Job.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Fetch the canonical job for a duplicate by URL. Returns null if not found.
  static Future<Job?> getJobByUrl(String url) async {
    if (url.isEmpty) return null;
    final encoded = Uri.encodeComponent(url);
    final res = await http.get(
      Uri.parse('$_base/jobs?select=$_jobColumns&url=eq.$encoded&limit=1'),
      headers: _headers,
    );
    if (res.statusCode != 200) return null;
    final list = jsonDecode(res.body) as List<dynamic>;
    if (list.isEmpty) return null;
    return Job.fromJson(list.first as Map<String, dynamic>);
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

  // ── Generic bot_state key/value ─────────────────────────────────────────

  static Future<String> getConfigValue(String key, String defaultValue) async {
    try {
      final res = await http.get(
        Uri.parse('$_base/bot_state?key=eq.$key&select=value&limit=1'),
        headers: _headers,
      );
      if (res.statusCode != 200) return defaultValue;
      final rows = jsonDecode(res.body) as List<dynamic>;
      return rows.isEmpty ? defaultValue : (rows[0]['value'] as String? ?? defaultValue);
    } catch (_) {
      return defaultValue;
    }
  }

  static Future<bool> setConfigValue(String key, String value) async {
    try {
      final res = await http.post(
        Uri.parse('$_base/bot_state'),
        headers: {..._headers, 'Prefer': 'resolution=merge-duplicates,return=minimal'},
        body: jsonEncode([{'key': key, 'value': value}]),
      );
      return res.statusCode == 200 || res.statusCode == 201;
    } catch (_) {
      return false;
    }
  }

  // ── CV profile ───────────────────────────────────────────────────────────

  /// Loads all cv_* keys from bot_state in one round-trip.
  static Future<Map<String, String>> getCvProfile() async {
    try {
      final res = await http.get(
        Uri.parse('$_base/bot_state?key=like.cv_%25&select=key,value'),
        headers: _headers,
      );
      if (res.statusCode != 200) return {};
      final rows = jsonDecode(res.body) as List<dynamic>;
      return {
        for (final r in rows)
          (r['key'] as String): (r['value'] as String? ?? ''),
      };
    } catch (_) {
      return {};
    }
  }

  // ── Easy Apply ────────────────────────────────────────────────────────────

  /// Stores an apply request as a JSON blob in bot_state.
  /// Key: apply_req_{jobId}
  static Future<bool> saveApplyRequest({
    required String jobId,
    required String jobUrl,
    required String jobTitle,
    required String company,
    required Map<String, dynamic> answers,
  }) async {
    final data = jsonEncode({
      'job_id':    jobId,
      'job_url':   jobUrl,
      'job_title': jobTitle,
      'company':   company,
      'answers':   answers,
      'status':    'pending',
      'created_at': DateTime.now().toUtc().toIso8601String(),
    });
    return setConfigValue('apply_req_$jobId', data);
  }

  /// Reads back a previously saved apply request.
  static Future<Map<String, dynamic>?> getApplyRequest(String jobId) async {
    final raw = await getConfigValue('apply_req_$jobId', '');
    if (raw.isEmpty) return null;
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return null;
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

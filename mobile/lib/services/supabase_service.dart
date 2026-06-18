import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';
import '../config.dart';
import '../models/job.dart';
import '../models/app_settings.dart';

class LinkedInProfile {
  final List<String> jobTitles;
  final List<String> locations;
  const LinkedInProfile({required this.jobTitles, required this.locations});
}

class SupabaseService {
  static const _base = '${Config.supabaseUrl}/rest/v1';

  static Map<String, String> get _headers {
    final session = Supabase.instance.client.auth.currentSession;
    final token = session?.accessToken ?? Config.supabaseKey;
    return {
      'apikey': Config.supabaseKey,
      'Authorization': 'Bearer $token',
      'Content-Type': 'application/json',
    };
  }

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

  /// Per-user job feed filtered by the signed-in user's preferences.
  static Future<List<Job>> listUserFeed({int limit = 200}) async {
    try {
      final res = await http.post(
        Uri.parse('$_base/rpc/user_jobs_feed'),
        headers: _headers,
        body: jsonEncode({'p_limit': limit}),
      );
      if (res.statusCode != 200) return [];
      final list = jsonDecode(res.body) as List<dynamic>;
      return list.map((e) => Job.fromJson(e as Map<String, dynamic>)).toList();
    } catch (_) {
      return [];
    }
  }

  /// Upsert a per-user job status into user_job_interactions.
  static Future<bool> updateJobInteraction(String jobId, String status) async {
    final userId = Supabase.instance.client.auth.currentUser?.id;
    if (userId == null) return false;
    try {
      final res = await http.post(
        Uri.parse('$_base/user_job_interactions'),
        headers: {
          ..._headers,
          'Prefer': 'resolution=merge-duplicates,return=minimal',
        },
        body: jsonEncode([
          {'user_id': userId, 'job_id': jobId, 'status': status},
        ]),
      );
      return res.statusCode == 200 || res.statusCode == 201;
    } catch (_) {
      return false;
    }
  }

  /// Load the signed-in user's preferences row.
  static Future<Map<String, dynamic>> getUserPreferences() async {
    final userId = Supabase.instance.client.auth.currentUser?.id;
    if (userId == null) return {};
    try {
      final res = await http.get(
        Uri.parse('$_base/user_preferences?user_id=eq.$userId&limit=1'),
        headers: _headers,
      );
      if (res.statusCode != 200) return {};
      final rows = jsonDecode(res.body) as List<dynamic>;
      return rows.isEmpty ? {} : rows.first as Map<String, dynamic>;
    } catch (_) {
      return {};
    }
  }

  /// Upsert keywords, locations, and min_score for the signed-in user.
  static Future<bool> saveUserPreferences({
    required List<String> keywords,
    required List<String> locations,
    required List<String> excludeKeywords,
    int? minScore,
    String alertFrequency = 'instant',
  }) async {
    final userId = Supabase.instance.client.auth.currentUser?.id;
    if (userId == null) return false;
    try {
      final body = <String, dynamic>{
        'user_id': userId,
        'keywords': keywords,
        'locations': locations,
        'exclude_keywords': excludeKeywords,
        'alert_frequency': alertFrequency,
      };
      if (minScore != null) body['min_score'] = minScore;
      final res = await http.post(
        Uri.parse('$_base/user_preferences'),
        headers: {
          ..._headers,
          'Prefer': 'resolution=merge-duplicates,return=minimal',
        },
        body: jsonEncode([body]),
      );
      return res.statusCode == 200 || res.statusCode == 201;
    } catch (_) {
      return false;
    }
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

  // ── LinkedIn URL fetch (onboarding) ─────────────────────────────────────

  /// Fetches a LinkedIn public profile page and extracts job title candidates
  /// and locations using client-side text parsing.
  static Future<LinkedInProfile?> fetchLinkedInUrl(String url) async {
    try {
      final res = await http.get(
        Uri.parse(url),
        headers: {
          'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
          'Accept-Language': 'en-US,en;q=0.9',
          'Accept':          'text/html,application/xhtml+xml,*/*;q=0.8',
        },
      ).timeout(const Duration(seconds: 12));
      if (res.statusCode != 200) return null;

      // Strip HTML tags to get plain text
      final text = res.body
          .replaceAll(RegExp(r'<script[\s\S]*?</script>', caseSensitive: false), ' ')
          .replaceAll(RegExp(r'<style[\s\S]*?</style>',   caseSensitive: false), ' ')
          .replaceAll(RegExp(r'<[^>]+>'), ' ')
          .replaceAll(RegExp(r'&amp;'),  '&')
          .replaceAll(RegExp(r'&nbsp;'), ' ')
          .replaceAll(RegExp(r'\s{2,}'), ' ')
          .trim();

      if (text.length < 50) return null;

      final candidates = text
          .split(RegExp(r'[\n,·|•]'))
          .map((s) => s.trim())
          .where((s) => s.length > 3 && s.length < 50)
          .where((s) => RegExp(r'^[A-Z]').hasMatch(s))
          .take(8)
          .toList();

      final autoLocs = const [
        'United Arab Emirates', 'Dubai', 'Abu Dhabi', 'Sharjah', 'Ajman',
        'Egypt', 'Saudi Arabia', 'Qatar', 'Kuwait',
      ].where((loc) => text.toLowerCase().contains(loc.toLowerCase())).toList();

      return LinkedInProfile(jobTitles: candidates, locations: autoLocs);
    } catch (_) {
      return null;
    }
  }

  // SECURITY: these fields are never uploaded — bot_state is readable with
  // the public anon key that ships in this app, so anything written here is
  // world-readable. Secrets live in GitHub Actions Secrets (cloud workers)
  // and settings.json (desktop) only.
  static const _secretSettingKeys = {
    'linkedin_cookie',
    'gmail_email',
    'gmail_app_password',
    'github_token',
  };

  static Future<bool> saveSettings(AppSettings s) async {
    try {
      final entries = s.toMap().entries
          .where((e) => !_secretSettingKeys.contains(e.key))
          .toList();
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

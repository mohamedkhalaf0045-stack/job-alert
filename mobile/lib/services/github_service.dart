import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config.dart';
import '../models/cloud_status.dart';
import 'supabase_service.dart';

class GitHubService {
  static const _base = 'https://api.github.com';

  // Runtime token — seeded from compile-time --dart-define, then overridden
  // by the value stored in Supabase (setting_github_token).  Updated whenever
  // the settings screen saves a new token.
  static String _token = Config.githubToken;

  /// Called once at app startup. Reads setting_github_token from Supabase and
  /// caches it so all subsequent API calls use the correct PAT.
  static Future<void> loadToken() async {
    try {
      final stored = await SupabaseService.getConfigValue('setting_github_token', '');
      if (stored.isNotEmpty) {
        _token = stored;
      }
    } catch (_) {}
  }

  /// Called by the settings screen after saving a new token.
  static void setToken(String token) => _token = token.trim();

  /// Returns the headers map.  Authorization is omitted when the token is empty
  /// so that unauthenticated requests to public repos work (GitHub returns 401
  /// for an *empty* Bearer token, but 200 for a request with NO auth header).
  static Map<String, String> get _headers {
    final h = <String, String>{
      'Accept': 'application/vnd.github+json',
    };
    if (_token.isNotEmpty) {
      h['Authorization'] = 'Bearer $_token';
    }
    return h;
  }

  static Future<CloudStatus> getCloudStatus() async {
    // 1. Get latest run
    final runsRes = await http.get(
      Uri.parse('$_base/repos/${Config.githubRepo}/actions/workflows/job-alert.yml/runs?per_page=1'),
      headers: _headers,
    );
    if (runsRes.statusCode != 200) {
      String errorMsg = 'API error (${runsRes.statusCode})';
      if (_token.isEmpty) {
        errorMsg = 'No GitHub token — add it in Settings';
      } else if (runsRes.statusCode == 401 || runsRes.statusCode == 403) {
        errorMsg = 'GitHub token invalid or expired';
      } else if (runsRes.statusCode >= 500) {
        errorMsg = 'GitHub service error';
      } else if (runsRes.statusCode == 404) {
        errorMsg = 'Repo / workflow not found';
      }
      return CloudStatus(lampColor: 'grey', lastRunTime: errorMsg);
    }

    final runsData = jsonDecode(runsRes.body) as Map<String, dynamic>;
    final runs = runsData['workflow_runs'] as List<dynamic>? ?? [];
    if (runs.isEmpty) {
      return const CloudStatus(lampColor: 'grey', lastRunTime: 'No runs yet');
    }

    final run = runs.first as Map<String, dynamic>;
    final runId      = run['id'] as int? ?? 0;
    final workflowId = run['workflow_id'] as int? ?? 0;
    final htmlUrl    = run['html_url'] as String? ?? '';
    final status     = run['status'] as String? ?? '';
    final conclusion = run['conclusion'] as String? ?? '';
    final createdAt  = run['created_at'] as String? ?? '';

    String lampColor;
    if (['in_progress', 'queued', 'waiting'].contains(status)) {
      lampColor = 'yellow';
    } else if (conclusion == 'success') {
      lampColor = 'green';
    } else if (conclusion.isNotEmpty) {
      lampColor = 'red';
    } else {
      lampColor = 'grey';
    }

    // 2. Check schedule enabled/disabled
    bool scheduleActive = true;
    if (workflowId > 0) {
      try {
        final wfRes = await http.get(
          Uri.parse('$_base/repos/${Config.githubRepo}/actions/workflows/$workflowId'),
          headers: _headers,
        );
        if (wfRes.statusCode == 200) {
          final wfData = jsonDecode(wfRes.body) as Map<String, dynamic>;
          scheduleActive = (wfData['state'] as String?) == 'active';
        }
      } catch (_) {}
    }

    // 3. Get job count from Supabase
    int jobCount = 0;
    try {
      final countRes = await http.get(
        Uri.parse('https://xsuqhjmonzcguedekqjt.supabase.co/rest/v1/jobs?select=job_id'),
        headers: {
          'apikey': Config.supabaseKey,
          'Authorization': 'Bearer ${Config.supabaseKey}',
          'Prefer': 'count=exact',
          'Range-Unit': 'items',
          'Range': '0-0',
        },
      );
      final range = countRes.headers['content-range'] ?? '';
      final parts = range.split('/');
      if (parts.length == 2) jobCount = int.tryParse(parts[1]) ?? 0;
    } catch (_) {}

    return CloudStatus(
      lampColor:      lampColor,
      lastRunTime:    createdAt.length >= 16 ? '${createdAt.substring(0, 10)} ${createdAt.substring(11, 16)} UTC' : createdAt,
      jobCount:       jobCount,
      scheduleActive: scheduleActive,
      runId:          runId,
      workflowId:     workflowId,
      htmlUrl:        htmlUrl,
      conclusion:     conclusion,
    );
  }

  static Future<bool> triggerRun(int workflowId) async {
    final res = await http.post(
      Uri.parse('$_base/repos/${Config.githubRepo}/actions/workflows/$workflowId/dispatches'),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: '{"ref":"main"}',
    );
    return res.statusCode == 204;
  }

  static Future<bool> cancelRun(int runId) async {
    final res = await http.post(
      Uri.parse('$_base/repos/${Config.githubRepo}/actions/runs/$runId/cancel'),
      headers: _headers,
    );
    return res.statusCode == 202;
  }

  /// Dispatch the easy-apply.yml workflow for the given jobId.
  static Future<bool> triggerEasyApply(String jobId) async {
    final res = await http.post(
      Uri.parse(
          '$_base/repos/${Config.githubRepo}/actions/workflows/easy-apply.yml/dispatches'),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: jsonEncode({'ref': 'main', 'inputs': {'job_id': jobId}}),
    );
    return res.statusCode == 204;
  }

  static Future<bool> toggleSchedule(int workflowId, bool currentlyActive) async {
    final action = currentlyActive ? 'disable' : 'enable';
    final res = await http.put(
      Uri.parse('$_base/repos/${Config.githubRepo}/actions/workflows/$workflowId/$action'),
      headers: _headers,
    );
    return res.statusCode == 204;
  }
}

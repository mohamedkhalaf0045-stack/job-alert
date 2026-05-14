import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config.dart';
import '../models/cloud_status.dart';

class GitHubService {
  static const _base = 'https://api.github.com';

  static Map<String, String> get _headers => {
        'Authorization': 'Bearer ${Config.githubToken}',
        'Accept': 'application/vnd.github+json',
      };

  static Future<CloudStatus> getCloudStatus() async {
    // 1. Get latest run
    final runsRes = await http.get(
      Uri.parse('$_base/repos/${Config.githubRepo}/actions/workflows/job-alert.yml/runs?per_page=1'),
      headers: _headers,
    );
    if (runsRes.statusCode != 200) {
      String errorMsg = 'API error';
      if (Config.githubToken.isEmpty) {
        errorMsg = 'No GitHub token configured';
      } else if (runsRes.statusCode == 401 || runsRes.statusCode == 403) {
        errorMsg = 'GitHub token invalid';
      } else if (runsRes.statusCode >= 500) {
        errorMsg = 'GitHub service error';
      } else if (runsRes.statusCode == 404) {
        errorMsg = 'Repo not found';
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

  static Future<bool> toggleSchedule(int workflowId, bool currentlyActive) async {
    final action = currentlyActive ? 'disable' : 'enable';
    final res = await http.put(
      Uri.parse('$_base/repos/${Config.githubRepo}/actions/workflows/$workflowId/$action'),
      headers: _headers,
    );
    return res.statusCode == 204;
  }
}

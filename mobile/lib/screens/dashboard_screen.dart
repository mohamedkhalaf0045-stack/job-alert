import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/cloud_status.dart';
import '../services/github_service.dart';
import '../services/supabase_service.dart';
import '../widgets/status_lamp.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late Future<CloudStatus> _statusFuture;
  late Future<Map<String, int>> _countsFuture;
  bool _actionLoading = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  void _refresh() => setState(() {
        _statusFuture = GitHubService.getCloudStatus();
        _countsFuture = SupabaseService.getJobCounts();
      });

  Future<void> _runAction(Future<bool> Function() action) async {
    setState(() => _actionLoading = true);
    try {
      await action();
      await Future.delayed(const Duration(seconds: 2));
    } finally {
      if (mounted) {
        setState(() => _actionLoading = false);
        _refresh();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _refresh(),
      child: FutureBuilder<CloudStatus>(
        future: _statusFuture,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text('Error: ${snap.error}'));
          }

          final s = snap.data!;
          final isRunning = s.lampColor == 'yellow';

          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              const SizedBox(height: 8),
              Center(child: StatusLamp(color: s.lampColor)),
              const SizedBox(height: 12),
              Center(
                child: Text(
                  _lampLabel(s.lampColor),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              const SizedBox(height: 20),
              _CloudStatsCard(status: s),
              const SizedBox(height: 12),
              FutureBuilder<Map<String, int>>(
                future: _countsFuture,
                builder: (ctx, cSnap) {
                  if (!cSnap.hasData) return const SizedBox.shrink();
                  return _JobCountsCard(counts: cSnap.data!);
                },
              ),
              const SizedBox(height: 24),
              if (_actionLoading)
                const Center(child: CircularProgressIndicator())
              else
                _ControlButtons(
                  status: s,
                  isRunning: isRunning,
                  onRunNow: () => _runAction(
                      () => GitHubService.triggerRun(s.workflowId)),
                  onCancel: () => _runAction(
                      () => GitHubService.cancelRun(s.runId)),
                  onOpenLogs: () async {
                    final uri = Uri.tryParse(s.htmlUrl);
                    if (uri != null) {
                      await launchUrl(uri,
                          mode: LaunchMode.externalApplication);
                    }
                  },
                  onToggleSchedule: () => _runAction(
                      () => GitHubService.toggleSchedule(
                          s.workflowId, s.scheduleActive)),
                ),
            ],
          );
        },
      ),
    );
  }

  String _lampLabel(String color) => switch (color) {
        'green'  => 'Last run succeeded',
        'yellow' => 'Running now...',
        'red'    => 'Last run failed',
        _        => 'Status unknown',
      };
}

// ── Cloud stats card ────────────────────────────────────────────────────────

class _CloudStatsCard extends StatelessWidget {
  final CloudStatus status;
  const _CloudStatsCard({required this.status});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 8),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _Stat(label: 'Last run', value: status.lastRunTime),
            _Stat(label: 'Total jobs', value: '${status.jobCount}'),
            _Stat(
              label: 'Schedule',
              value: status.scheduleActive ? 'Active' : 'Paused',
              valueColor:
                  status.scheduleActive ? Colors.green : Colors.orange,
            ),
          ],
        ),
      ),
    );
  }
}

// ── Job counts card ─────────────────────────────────────────────────────────

class _JobCountsCard extends StatelessWidget {
  final Map<String, int> counts;
  const _JobCountsCard({required this.counts});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _CountChip('New',       counts['new'] ?? 0,       const Color(0xFFF0B400)),
            _CountChip('Applied',   counts['applied'] ?? 0,   Colors.blue),
            _CountChip('Saved',     counts['saved'] ?? 0,     Colors.green),
            _CountChip('Dismissed', counts['dismissed'] ?? 0, Colors.grey),
          ],
        ),
      ),
    );
  }
}

class _CountChip extends StatelessWidget {
  final String label;
  final int count;
  final Color color;
  const _CountChip(this.label, this.count, this.color);

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text('$count',
            style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.bold,
                color: color)),
        Text(label,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Colors.grey)),
      ],
    );
  }
}

// ── Shared stat widget ───────────────────────────────────────────────────────

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  const _Stat({required this.label, required this.value, this.valueColor});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Colors.grey)),
        const SizedBox(height: 4),
        Text(value,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                fontWeight: FontWeight.bold, color: valueColor)),
      ],
    );
  }
}

// ── Control buttons ──────────────────────────────────────────────────────────

class _ControlButtons extends StatelessWidget {
  final CloudStatus status;
  final bool isRunning;
  final VoidCallback onRunNow;
  final VoidCallback onCancel;
  final VoidCallback onOpenLogs;
  final VoidCallback onToggleSchedule;

  const _ControlButtons({
    required this.status,
    required this.isRunning,
    required this.onRunNow,
    required this.onCancel,
    required this.onOpenLogs,
    required this.onToggleSchedule,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: isRunning ? null : onRunNow,
              icon: const Icon(Icons.play_arrow),
              label: const Text('Run Now'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton.icon(
              onPressed: isRunning ? onCancel : null,
              icon: const Icon(Icons.stop),
              label: const Text('Cancel'),
              style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
            ),
          ),
        ]),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: status.htmlUrl.isNotEmpty ? onOpenLogs : null,
              icon: const Icon(Icons.open_in_new),
              label: const Text('Open Logs'),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: OutlinedButton.icon(
              onPressed: onToggleSchedule,
              icon: Icon(
                  status.scheduleActive ? Icons.pause : Icons.schedule),
              label: Text(status.scheduleActive ? 'Pause' : 'Resume'),
            ),
          ),
        ]),
      ],
    );
  }
}

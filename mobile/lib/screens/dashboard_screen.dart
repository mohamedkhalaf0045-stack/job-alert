import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/cloud_status.dart';
import '../services/github_service.dart';
import '../services/supabase_service.dart';
import '../services/update_service.dart';
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

  UpdateInfo? _updateInfo;
  bool _downloading   = false;
  double _dlProgress  = 0;

  @override
  void initState() {
    super.initState();
    _refresh();
    _checkUpdate();
  }

  void _refresh() => setState(() {
        _statusFuture = GitHubService.getCloudStatus();
        _countsFuture = SupabaseService.getJobCounts();
      });

  Future<void> _checkUpdate() async {
    final info = await UpdateService.checkForUpdate();
    if (mounted) setState(() => _updateInfo = info);
  }

  Future<void> _doUpdate() async {
    if (_updateInfo == null) return;
    setState(() { _downloading = true; _dlProgress = 0; });

    final error = await UpdateService.downloadAndInstall(
      _updateInfo!.apkUrl,
      (p) { if (mounted) setState(() => _dlProgress = p); },
    );

    if (mounted) {
      setState(() => _downloading = false);
      if (error != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Update failed: $error'), backgroundColor: Colors.red),
        );
      }
    }
  }

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
      onRefresh: () async { _refresh(); await _checkUpdate(); },
      child: FutureBuilder<CloudStatus>(
        future: _statusFuture,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text('Error: ${snap.error}'));
          }

          final s         = snap.data!;
          final isRunning = s.lampColor == 'yellow';

          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              // ── Update banner ──────────────────────────────────────────────
              if (_updateInfo != null) _UpdateBanner(
                info:        _updateInfo!,
                downloading: _downloading,
                progress:    _dlProgress,
                onUpdate:    _doUpdate,
              ),
              if (_updateInfo != null) const SizedBox(height: 16),

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

// ── Update banner ────────────────────────────────────────────────────────────

class _UpdateBanner extends StatelessWidget {
  final UpdateInfo info;
  final bool downloading;
  final double progress;
  final VoidCallback onUpdate;

  const _UpdateBanner({
    required this.info,
    required this.downloading,
    required this.progress,
    required this.onUpdate,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      color: Theme.of(context).colorScheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.system_update, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Update available — ${info.versionName}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                if (!downloading)
                  FilledButton.icon(
                    onPressed: onUpdate,
                    icon: const Icon(Icons.download, size: 18),
                    label: const Text('Update'),
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 14, vertical: 8),
                      textStyle: const TextStyle(fontSize: 13),
                    ),
                  ),
              ],
            ),
            if (downloading) ...[
              const SizedBox(height: 10),
              LinearProgressIndicator(value: progress == 0 ? null : progress),
              const SizedBox(height: 4),
              Text(
                progress == 0
                    ? 'Downloading...'
                    : 'Downloading… ${(progress * 100).toStringAsFixed(0)}%',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ── Cloud stats card ────────────────────────────────────────────────────────

class _CloudStatsCard extends StatelessWidget {
  final CloudStatus status;
  const _CloudStatsCard({required this.status});

  @override
  Widget build(BuildContext context) {
    final isError = status.lastRunTime.contains('error') ||
        status.lastRunTime.contains('Error') ||
        status.lastRunTime.contains('No') ||
        status.lastRunTime.contains('invalid');

    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 8),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: [
            _Stat(
              label: 'Status',
              value: status.lastRunTime,
              valueColor: isError ? Colors.red : null,
              isError: isError,
            ),
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
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
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
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.3), width: 1),
      ),
      child: Column(
        children: [
          Text('$count',
              style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  color: color)),
          const SizedBox(height: 4),
          Text(label,
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: Colors.grey)),
        ],
      ),
    );
  }
}

// ── Shared stat widget ───────────────────────────────────────────────────────

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  final bool isError;
  const _Stat({
    required this.label,
    required this.value,
    this.valueColor,
    this.isError = false,
  });

  @override
  Widget build(BuildContext context) {
    final valueText = Text(
      value,
      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
          fontWeight: FontWeight.bold, color: valueColor),
      maxLines: 2,
      overflow: TextOverflow.ellipsis,
      textAlign: TextAlign.center,
    );

    return Column(
      children: [
        Text(label,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Colors.grey)),
        const SizedBox(height: 4),
        isError
            ? Tooltip(
                message: value,
                child: valueText,
              )
            : valueText,
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

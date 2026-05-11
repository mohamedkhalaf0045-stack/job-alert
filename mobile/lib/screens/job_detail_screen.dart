import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/job.dart';
import '../services/supabase_service.dart';

class JobDetailScreen extends StatefulWidget {
  final Job job;
  const JobDetailScreen({super.key, required this.job});

  @override
  State<JobDetailScreen> createState() => _JobDetailScreenState();
}

class _JobDetailScreenState extends State<JobDetailScreen> {
  late String _status;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _status = widget.job.status;
  }

  Future<void> _setStatus(String newStatus) async {
    setState(() => _saving = true);
    await SupabaseService.updateJobStatus(widget.job.url, newStatus);
    if (mounted) setState(() { _status = newStatus; _saving = false; });
  }

  @override
  Widget build(BuildContext context) {
    final job = widget.job;
    return Scaffold(
      appBar: AppBar(title: const Text('Job Detail')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(job.title,
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text(job.company,
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(color: Colors.grey[700])),
          const SizedBox(height: 4),
          Text(job.location,
              style: Theme.of(context).textTheme.bodyMedium),
          const SizedBox(height: 12),
          Row(children: [
            _SourceBadge(source: job.source),
            const SizedBox(width: 8),
            Chip(
              label: Text(_status,
                  style: const TextStyle(fontSize: 12, color: Colors.white)),
              backgroundColor: _statusColor(_status),
              padding: EdgeInsets.zero,
            ),
          ]),
          const SizedBox(height: 16),
          if (job.datePosted != null)
            _InfoRow('Posted', _formatDate(job.datePosted!)),
          if (job.dateCollected != null)
            _InfoRow('Collected', _formatDate(job.dateCollected!)),
          const SizedBox(height: 16),
          if (job.url.isNotEmpty)
            OutlinedButton.icon(
              onPressed: () async {
                final uri = Uri.tryParse(job.url);
                if (uri != null) {
                  await launchUrl(uri, mode: LaunchMode.externalApplication);
                }
              },
              icon: const Icon(Icons.open_in_new),
              label: const Text('Open in browser'),
            ),
          if (job.llmScore != null) ...[
            const SizedBox(height: 16),
            _AiMatchCard(score: job.llmScore!, summary: job.llmSummary),
          ],
          const SizedBox(height: 32),
          const Text('Update status:',
              style: TextStyle(fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          if (_saving)
            const Center(child: CircularProgressIndicator())
          else
            _ActionButtons(
              current: _status,
              onApply:   () => _setStatus('applied'),
              onSave:    () => _setStatus('saved'),
              onDismiss: () => _setStatus('dismissed'),
              onReset:   () => _setStatus('new'),
            ),
        ],
      ),
    );
  }

  Color _statusColor(String s) => switch (s) {
        'applied'   => Colors.blue,
        'saved'     => Colors.green,
        'dismissed' => Colors.grey,
        _           => const Color(0xFFF0B400),
      };

  String _formatDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  const _InfoRow(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(children: [
        Text('$label: ',
            style: const TextStyle(fontWeight: FontWeight.bold)),
        Text(value),
      ]),
    );
  }
}

class _SourceBadge extends StatelessWidget {
  final String source;
  const _SourceBadge({required this.source});

  @override
  Widget build(BuildContext context) {
    final isLinkedIn = source.toLowerCase().contains('linkedin');
    return Chip(
      label: Text(source,
          style: const TextStyle(fontSize: 12, color: Colors.white)),
      backgroundColor: isLinkedIn ? Colors.blue : Colors.orange,
      padding: EdgeInsets.zero,
    );
  }
}

class _AiMatchCard extends StatelessWidget {
  final int score;
  final String? summary;
  const _AiMatchCard({required this.score, this.summary});

  Color get _color {
    if (score >= 8) return Colors.green;
    if (score >= 5) return const Color(0xFFF0B400);
    return Colors.grey;
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      color: _color.withOpacity(0.1),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(shape: BoxShape.circle, color: _color),
              alignment: Alignment.center,
              child: Text(
                '$score',
                style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.bold),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('AI Match: $score/10',
                      style: TextStyle(
                          fontWeight: FontWeight.bold, color: _color)),
                  if (summary != null && summary!.isNotEmpty)
                    Text(summary!,
                        style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionButtons extends StatelessWidget {
  final String current;
  final VoidCallback onApply;
  final VoidCallback onSave;
  final VoidCallback onDismiss;
  final VoidCallback onReset;

  const _ActionButtons({
    required this.current,
    required this.onApply,
    required this.onSave,
    required this.onDismiss,
    required this.onReset,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: current != 'applied' ? onApply : null,
              icon: const Icon(Icons.check_circle),
              label: const Text('Applied'),
              style: FilledButton.styleFrom(backgroundColor: Colors.blue),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: FilledButton.icon(
              onPressed: current != 'saved' ? onSave : null,
              icon: const Icon(Icons.bookmark),
              label: const Text('Save'),
              style: FilledButton.styleFrom(backgroundColor: Colors.green),
            ),
          ),
        ]),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(
            child: OutlinedButton.icon(
              onPressed: current != 'dismissed' ? onDismiss : null,
              icon: const Icon(Icons.close),
              label: const Text('Dismiss'),
              style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: OutlinedButton.icon(
              onPressed: current != 'new' ? onReset : null,
              icon: const Icon(Icons.refresh),
              label: const Text('Reset to New'),
            ),
          ),
        ]),
      ],
    );
  }
}

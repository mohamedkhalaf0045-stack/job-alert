import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

  Future<void> _copyCoverLetter() async {
    final draft = widget.job.coverLetterDraft ?? '';
    if (draft.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: draft));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Cover letter copied to clipboard'),
          duration: Duration(seconds: 2),
        ),
      );
    }
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

          // Phase 3: this job is a duplicate of another
          if (job.isDuplicate) ...[
            const SizedBox(height: 16),
            _DuplicateBanner(canonicalUrl: job.duplicateOfUrl!),
          ],

          // Phase 2: multi-criteria breakdown
          if (job.llmScore != null) ...[
            const SizedBox(height: 16),
            _AiMatchCard(job: job),
          ],

          // Phase 5: cover-letter draft
          if (job.hasCoverLetter) ...[
            const SizedBox(height: 16),
            _CoverLetterCard(
              draft: job.coverLetterDraft!,
              onCopy: _copyCoverLetter,
            ),
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

  String _formatDate(DateTime d) {
    final local = d.isUtc ? d.toLocal() : d;
    final offset = DateTime.now().timeZoneOffset;
    final sign = offset.isNegative ? '-' : '+';
    final h = offset.inMinutes.abs() ~/ 60;
    final tzLabel = 'UTC$sign$h';
    return '${local.year}-${local.month.toString().padLeft(2, '0')}-${local.day.toString().padLeft(2, '0')} '
        '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')} ($tzLabel)';
  }
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

/// Phase 2: full multi-criteria breakdown card.
/// Falls back to the legacy single-score layout if Phase 2 columns are null.
class _AiMatchCard extends StatelessWidget {
  final Job job;
  const _AiMatchCard({required this.job});

  Color _scoreColor(int s) {
    if (s >= 8) return Colors.green;
    if (s >= 5) return const Color(0xFFF0B400);
    return Colors.grey;
  }

  @override
  Widget build(BuildContext context) {
    final score = job.llmScore!;
    final color = _scoreColor(score);
    return Card(
      color: color.withOpacity(0.08),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header row: big score circle + label + reasoning
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(
                width: 44, height: 44,
                decoration: BoxDecoration(shape: BoxShape.circle, color: color),
                alignment: Alignment.center,
                child: Text('$score',
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.bold)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('AI Match: $score/10',
                        style: TextStyle(
                            fontWeight: FontWeight.bold, color: color)),
                    if ((job.llmSummary ?? '').isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(job.llmSummary!,
                          style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ],
                ),
              ),
            ]),
            // Sub-scores (Phase 2)
            if (job.hasBreakdown) ...[
              const SizedBox(height: 12),
              _SubScoreRow(label: 'Skills',     value: job.skillsMatch),
              _SubScoreRow(label: 'Experience', value: job.experienceMatch),
              _SubScoreRow(label: 'Location',   value: job.locationMatch),
              _SubScoreRow(label: 'Seniority',  value: job.seniorityMatch),
            ],
            // Matched / missing skills chips
            if (job.matchedSkills.isNotEmpty) ...[
              const SizedBox(height: 12),
              _ChipGroup(
                label: 'Matched',
                items: job.matchedSkills,
                color: Colors.green.shade700,
                bg: Colors.green.shade50,
              ),
            ],
            if (job.missingSkills.isNotEmpty) ...[
              const SizedBox(height: 8),
              _ChipGroup(
                label: 'Missing',
                items: job.missingSkills,
                color: Colors.orange.shade800,
                bg: Colors.orange.shade50,
              ),
            ],
            if (job.redFlags.isNotEmpty) ...[
              const SizedBox(height: 8),
              _ChipGroup(
                label: 'Red flags',
                items: job.redFlags,
                color: Colors.red.shade700,
                bg: Colors.red.shade50,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SubScoreRow extends StatelessWidget {
  final String label;
  final int? value;
  const _SubScoreRow({required this.label, required this.value});

  Color _color(int s) {
    if (s >= 8) return Colors.green;
    if (s >= 5) return const Color(0xFFF0B400);
    return Colors.red.shade400;
  }

  @override
  Widget build(BuildContext context) {
    final v = value ?? 0;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        SizedBox(
          width: 76,
          child: Text(label,
              style: const TextStyle(
                  fontSize: 12, fontWeight: FontWeight.w600)),
        ),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: v / 10.0,
              minHeight: 8,
              backgroundColor: Colors.grey.shade200,
              valueColor: AlwaysStoppedAnimation(_color(v)),
            ),
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          width: 32,
          child: Text('$v/10',
              textAlign: TextAlign.right,
              style: const TextStyle(fontSize: 12)),
        ),
      ]),
    );
  }
}

class _ChipGroup extends StatelessWidget {
  final String label;
  final List<String> items;
  final Color color;
  final Color bg;
  const _ChipGroup({
    required this.label,
    required this.items,
    required this.color,
    required this.bg,
  });

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label,
          style: TextStyle(
              fontSize: 11, fontWeight: FontWeight.bold, color: color)),
      const SizedBox(height: 4),
      Wrap(
        spacing: 6, runSpacing: 4,
        children: items.map((s) => Chip(
          label: Text(s, style: TextStyle(fontSize: 11, color: color)),
          backgroundColor: bg,
          side: BorderSide(color: color.withOpacity(0.3)),
          padding: const EdgeInsets.symmetric(horizontal: 6),
          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          visualDensity: VisualDensity.compact,
        )).toList(),
      ),
    ]);
  }
}

/// Phase 5: cover-letter draft card with copy button.
class _CoverLetterCard extends StatefulWidget {
  final String draft;
  final VoidCallback onCopy;
  const _CoverLetterCard({required this.draft, required this.onCopy});

  @override
  State<_CoverLetterCard> createState() => _CoverLetterCardState();
}

class _CoverLetterCardState extends State<_CoverLetterCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: Colors.blue.shade50,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.description, color: Colors.blue),
              const SizedBox(width: 8),
              Text('Cover letter draft',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: Colors.blue.shade900)),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.copy, size: 20),
                tooltip: 'Copy to clipboard',
                onPressed: widget.onCopy,
              ),
              IconButton(
                icon: Icon(_expanded ? Icons.expand_less : Icons.expand_more,
                    size: 22),
                tooltip: _expanded ? 'Collapse' : 'Show full draft',
                onPressed: () => setState(() => _expanded = !_expanded),
              ),
            ]),
            const SizedBox(height: 4),
            Text(
              widget.draft,
              maxLines: _expanded ? null : 4,
              overflow: _expanded ? TextOverflow.visible : TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 13, height: 1.4),
            ),
            const SizedBox(height: 4),
            Text(
              'AI-generated. Read and edit before sending.',
              style: TextStyle(
                  fontSize: 11,
                  fontStyle: FontStyle.italic,
                  color: Colors.grey.shade700),
            ),
          ],
        ),
      ),
    );
  }
}

/// Phase 3: banner shown when this job links to a canonical duplicate.
class _DuplicateBanner extends StatelessWidget {
  final String canonicalUrl;
  const _DuplicateBanner({required this.canonicalUrl});

  @override
  Widget build(BuildContext context) {
    return Card(
      color: Colors.grey.shade200,
      child: ListTile(
        leading: const Icon(Icons.copy_all, color: Colors.grey),
        title: const Text('Duplicate listing',
            style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
        subtitle: Text(
          'Already seen on another source. Open the original below.',
          style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
        ),
        trailing: IconButton(
          icon: const Icon(Icons.open_in_new),
          tooltip: 'Open canonical version',
          onPressed: () async {
            final uri = Uri.tryParse(canonicalUrl);
            if (uri != null) {
              await launchUrl(uri, mode: LaunchMode.externalApplication);
            }
          },
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

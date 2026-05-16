import 'package:flutter/material.dart';
import '../models/job.dart';

class JobCard extends StatelessWidget {
  final Job job;
  const JobCard({super.key, required this.job});

  Color get _statusColor => switch (job.status) {
        'applied'   => Colors.blue,
        'saved'     => Colors.green,
        'dismissed' => Colors.grey,
        _           => const Color(0xFFF0B400),
      };

  Color get _sourceColor =>
      job.source.toLowerCase().contains('linkedin') ? Colors.blue : Colors.orange;

  Color _scoreColor(int score) {
    if (score >= 8) return Colors.green.shade600;
    if (score >= 5) return const Color(0xFFF0B400);
    return Colors.grey.shade500;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasScore = job.llmScore != null;
    final hasSummary = (job.llmSummary ?? '').isNotEmpty;
    final hasMissing = job.missingSkills.isNotEmpty;
    final hasFlags   = job.redFlags.isNotEmpty;
    final hasExtras  = hasMissing || hasFlags;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      elevation: 1.5,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Status colour bar
            Container(
              width: 4,
              decoration: BoxDecoration(
                color: _statusColor,
                borderRadius:
                    const BorderRadius.horizontal(left: Radius.circular(8)),
              ),
            ),

            // Main content
            Expanded(
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Text block
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // Title
                          Text(
                            job.title,
                            style: theme.textTheme.bodyMedium?.copyWith(
                                fontWeight: FontWeight.bold),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          const SizedBox(height: 2),

                          // Company · Location
                          Text(
                            '${job.company}  •  ${job.location}',
                            style: theme.textTheme.bodySmall?.copyWith(
                                color: Colors.grey.shade600),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),

                          // AI summary — only when scored
                          if (hasSummary) ...[
                            const SizedBox(height: 4),
                            Text(
                              job.llmSummary!,
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: Colors.grey.shade700,
                                fontStyle: FontStyle.italic,
                              ),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],

                          // Missing skills + red flags hints
                          if (hasExtras) ...[
                            const SizedBox(height: 4),
                            Wrap(
                              spacing: 4,
                              runSpacing: 2,
                              children: [
                                if (hasMissing)
                                  _HintChip(
                                    icon: Icons.bookmark_remove_outlined,
                                    label: 'Missing: ${job.missingSkills.take(3).join(', ')}',
                                    color: Colors.red.shade400,
                                  ),
                                if (hasFlags)
                                  _HintChip(
                                    icon: Icons.warning_amber_outlined,
                                    label: '${job.redFlags.length} flag${job.redFlags.length > 1 ? "s" : ""}',
                                    color: Colors.orange.shade600,
                                  ),
                              ],
                            ),
                          ],
                        ],
                      ),
                    ),

                    const SizedBox(width: 8),

                    // Right column: badge + source + matched + date
                    Column(
                      mainAxisAlignment: MainAxisAlignment.start,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        // Score badge + source chip in a row
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (job.hasCoverLetter)
                              const Padding(
                                padding: EdgeInsets.only(right: 4),
                                child: Icon(Icons.description,
                                    size: 16, color: Colors.blue),
                              ),
                            if (hasScore) ...[
                              _ScoreBadge(
                                  score: job.llmScore!,
                                  color: _scoreColor(job.llmScore!)),
                              const SizedBox(width: 4),
                            ],
                            _SourceChip(
                                label: _shortSource(job.source),
                                color: _sourceColor),
                          ],
                        ),
                        const SizedBox(height: 4),

                        // Matched skills count
                        if (job.matchedSkills.isNotEmpty)
                          Text(
                            '✓ ${job.matchedSkills.length} matched',
                            style: TextStyle(
                                fontSize: 10,
                                color: Colors.green.shade700,
                                fontWeight: FontWeight.w600),
                          ),

                        // Date
                        if (job.datePosted != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child: Text(
                              _daysAgo(job.datePosted!),
                              style: theme.textTheme.bodySmall?.copyWith(
                                  color: Colors.grey.shade500),
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _shortSource(String source) {
    final s = source.toLowerCase();
    if (s.contains('linkedin')) return 'LI';
    if (s.contains('indeed'))   return 'IN';
    if (s.contains('adzuna'))   return 'AZ';
    if (s.contains('glassdoor')) return 'GD';
    if (s.contains('gmail'))    return 'GM';
    if (s.contains('web'))      return 'WB';
    return source.substring(0, source.length.clamp(0, 2)).toUpperCase();
  }

  String _daysAgo(DateTime d) {
    final diff = DateTime.now().difference(d).inDays;
    if (diff == 0) return 'Today';
    if (diff == 1) return '1d ago';
    return '${diff}d ago';
  }
}

// ── Widgets ──────────────────────────────────────────────────────────────────

class _ScoreBadge extends StatelessWidget {
  final int score;
  final Color color;
  const _ScoreBadge({required this.score, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: color,
        boxShadow: [
          BoxShadow(
              color: color.withOpacity(0.35),
              blurRadius: 4,
              offset: const Offset(0, 1)),
        ],
      ),
      alignment: Alignment.center,
      child: Text(
        '$score',
        style: const TextStyle(
            color: Colors.white,
            fontSize: 12,
            fontWeight: FontWeight.bold,
            height: 1),
      ),
    );
  }
}

class _SourceChip extends StatelessWidget {
  final String label;
  final Color color;
  const _SourceChip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        label,
        style: const TextStyle(
            color: Colors.white,
            fontSize: 10,
            fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _HintChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  const _HintChip(
      {required this.icon, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 10, color: color),
        const SizedBox(width: 2),
        Text(
          label,
          style: TextStyle(
              fontSize: 10, color: color, fontWeight: FontWeight.w500),
        ),
      ],
    );
  }
}

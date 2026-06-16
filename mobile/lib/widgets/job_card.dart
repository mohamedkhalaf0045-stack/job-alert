import 'package:flutter/material.dart';
import '../models/job.dart';
import '../main.dart' show kAccent, kFg, kFg2, kMuted, kMeta, kSuccess, kWarn, kDanger;

class JobCard extends StatelessWidget {
  final Job job;
  const JobCard({super.key, required this.job});

  Color get _statusColor => switch (job.status) {
        'applied'   => kSuccess,
        'saved'     => kAccent,
        'dismissed' => kMeta,
        _           => kWarn,
      };

  Color get _sourceColor {
    final s = job.source.toLowerCase();
    if (s.contains('linkedin')) return const Color(0xFF0A66C2);
    if (s.contains('indeed'))   return const Color(0xFF2164F3);
    if (s.contains('adzuna'))   return const Color(0xFFD1003F);
    if (s.contains('gmail'))    return const Color(0xFFEA4335);
    return kMuted;
  }

  Color _scoreColor(int score) {
    if (score >= 8) return kSuccess;
    if (score >= 5) return kWarn;
    return kMuted;
  }

  @override
  Widget build(BuildContext context) {
    final hasScore   = job.llmScore != null;
    final hasSummary = (job.llmSummary ?? '').isNotEmpty;
    final hasMissing = job.missingSkills.isNotEmpty;
    final hasFlags   = job.redFlags.isNotEmpty;
    final hasExtras  = hasMissing || hasFlags;

    return Card(
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Status bar
            Container(
              width: 3,
              decoration: BoxDecoration(
                color: _statusColor,
                borderRadius: const BorderRadius.horizontal(left: Radius.circular(10)),
              ),
            ),

            // Content
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
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
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: kFg,
                              letterSpacing: -0.2,
                              height: 1.3,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          const SizedBox(height: 2),

                          // Company · Location
                          Text(
                            '${job.company}  ·  ${job.location}',
                            style: const TextStyle(
                              fontSize: 12,
                              color: kMuted,
                              height: 1.3,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),

                          // AI summary
                          if (hasSummary) ...[
                            const SizedBox(height: 4),
                            Text(
                              job.llmSummary!,
                              style: const TextStyle(
                                fontSize: 12,
                                color: kFg2,
                                fontStyle: FontStyle.italic,
                                height: 1.4,
                              ),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],

                          // Missing skills / flags
                          if (hasExtras) ...[
                            const SizedBox(height: 5),
                            Wrap(
                              spacing: 4,
                              runSpacing: 2,
                              children: [
                                if (hasMissing)
                                  _HintChip(
                                    icon: Icons.bookmark_remove_outlined,
                                    label: 'Missing: ${job.missingSkills.take(3).join(', ')}',
                                    color: kDanger,
                                  ),
                                if (hasFlags)
                                  _HintChip(
                                    icon: Icons.warning_amber_outlined,
                                    label: '${job.redFlags.length} flag${job.redFlags.length > 1 ? "s" : ""}',
                                    color: kWarn,
                                  ),
                              ],
                            ),
                          ],
                        ],
                      ),
                    ),

                    const SizedBox(width: 8),

                    // Right column: score, source, matched, date
                    Column(
                      mainAxisAlignment: MainAxisAlignment.start,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (job.hasCoverLetter)
                              const Padding(
                                padding: EdgeInsets.only(right: 4),
                                child: Icon(Icons.description, size: 14, color: kAccent),
                              ),
                            if (hasScore) ...[
                              _ScoreBadge(
                                score: job.llmScore!,
                                color: _scoreColor(job.llmScore!),
                              ),
                              const SizedBox(width: 4),
                            ],
                            _SourceChip(
                              label: _shortSource(job.source),
                              color: _sourceColor,
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),

                        if (job.matchedSkills.isNotEmpty)
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.check_circle_outline, size: 10, color: kSuccess),
                              const SizedBox(width: 2),
                              Text(
                                '${job.matchedSkills.length} matched',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: kSuccess,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),

                        if (job.datePosted != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child: Text(
                              _daysAgo(job.datePosted!),
                              style: const TextStyle(fontSize: 11, color: kMeta),
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
    if (s.contains('linkedin'))   return 'LI';
    if (s.contains('indeed'))     return 'IN';
    if (s.contains('adzuna'))     return 'AZ';
    if (s.contains('glassdoor'))  return 'GD';
    if (s.contains('gmail'))      return 'GM';
    if (s.contains('web'))        return 'WB';
    return source.substring(0, source.length.clamp(0, 2)).toUpperCase();
  }

  String _daysAgo(DateTime d) {
    final diff = DateTime.now().difference(d).inDays;
    if (diff == 0) return 'Today';
    if (diff == 1) return '1d ago';
    return '${diff}d ago';
  }
}

// ── Sub-widgets ───────────────────────────────────────────────────────────────

class _ScoreBadge extends StatelessWidget {
  final int score;
  final Color color;
  const _ScoreBadge({required this.score, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 28,
      height: 28,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      alignment: Alignment.center,
      child: Text(
        '$score',
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w700,
          height: 1,
        ),
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
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.22)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _HintChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  const _HintChip({required this.icon, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 10, color: color),
        const SizedBox(width: 2),
        Text(
          label,
          style: TextStyle(fontSize: 10, color: color, fontWeight: FontWeight.w500),
        ),
      ],
    );
  }
}

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
    if (score >= 8) return Colors.green;
    if (score >= 5) return const Color(0xFFF0B400);
    return Colors.grey;
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(width: 4, color: _statusColor),
            Expanded(
              child: ListTile(
                title: Text(job.title,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis),
                subtitle: Text('${job.company}  •  ${job.location}',
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                trailing: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (job.hasCoverLetter)
                          const Padding(
                            padding: EdgeInsets.only(right: 4),
                            child: Icon(Icons.description,
                                size: 16, color: Colors.blue),
                          ),
                        if (job.llmScore != null) ...[
                          _ScoreBadge(score: job.llmScore!, color: _scoreColor(job.llmScore!)),
                          const SizedBox(width: 4),
                        ],
                        Chip(
                          label: Text(job.source,
                              style: const TextStyle(fontSize: 10, color: Colors.white)),
                          backgroundColor: _sourceColor,
                          padding: EdgeInsets.zero,
                          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                      ],
                    ),
                    if (job.matchedSkills.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(
                          '${job.matchedSkills.length} matched',
                          style: TextStyle(
                              fontSize: 10,
                              color: Colors.green.shade700,
                              fontWeight: FontWeight.w600),
                        ),
                      ),
                    if (job.datePosted != null)
                      Text(
                        _daysAgo(job.datePosted!),
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: Colors.grey),
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

  String _daysAgo(DateTime d) {
    final diff = DateTime.now().difference(d).inDays;
    if (diff == 0) return 'Today';
    if (diff == 1) return '1d ago';
    return '${diff}d ago';
  }
}

class _ScoreBadge extends StatelessWidget {
  final int score;
  final Color color;
  const _ScoreBadge({required this.score, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 28,
      height: 28,
      decoration: BoxDecoration(shape: BoxShape.circle, color: color),
      alignment: Alignment.center,
      child: Text(
        '$score',
        style: const TextStyle(
            color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import '../models/job.dart';
import '../services/supabase_service.dart';
import '../widgets/job_card.dart';
import 'job_detail_screen.dart';

// ── Tab definitions ───────────────────────────────────────────────────────────
//
//  Each tab is a (label, status-filter, sort-mode, loader) tuple.
//  sort-mode:  'date'    → newest first (default)
//              'new'     → unscored first, then high-score first, then newest
//              'score'   → high-score first, then newest
enum _Sort { date, newFirst, score }

class _TabDef {
  final String label;
  final String? status;   // null = all statuses
  final _Sort sort;
  final bool scoredOnly;  // true for the "Scored" tab

  const _TabDef(this.label, this.status, this.sort, {this.scoredOnly = false});
}

const _tabs = [
  _TabDef('All',     null,      _Sort.date),
  _TabDef('New',     'new',     _Sort.newFirst),
  _TabDef('Scored',  null,      _Sort.score,   scoredOnly: true),
  _TabDef('Applied', 'applied', _Sort.date),
  _TabDef('Saved',   'saved',   _Sort.date),
];

// ── Screen ────────────────────────────────────────────────────────────────────

class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key});

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabCtrl;
  final List<Future<List<Job>>?> _futures = List.filled(_tabs.length, null);

  @override
  void initState() {
    super.initState();
    _tabCtrl = TabController(length: _tabs.length, vsync: this);
    _tabCtrl.addListener(() {
      if (!_tabCtrl.indexIsChanging) _ensureLoaded(_tabCtrl.index);
    });
    _ensureLoaded(0);
  }

  @override
  void dispose() {
    _tabCtrl.dispose();
    super.dispose();
  }

  Future<List<Job>> _loadTab(int idx) {
    final t = _tabs[idx];
    if (t.scoredOnly) {
      return SupabaseService.listScoredJobs();
    }
    return SupabaseService.listJobs(status: t.status);
  }

  void _ensureLoaded(int idx) {
    if (_futures[idx] == null) {
      setState(() => _futures[idx] = _loadTab(idx));
    }
  }

  void _refreshTab(int idx) {
    setState(() => _futures[idx] = _loadTab(idx));
  }

  void _invalidateAll() {
    setState(() {
      for (int i = 0; i < _futures.length; i++) {
        _futures[i] = _loadTab(i);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        TabBar(
          controller: _tabCtrl,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: _tabs.map((t) => Tab(text: t.label)).toList(),
        ),
        Expanded(
          child: TabBarView(
            controller: _tabCtrl,
            children: List.generate(_tabs.length, (i) {
              return _JobList(
                future: _futures[i],
                sort: _tabs[i].sort,
                onRefresh: () => _refreshTab(i),
                onJobStatusChanged: _invalidateAll,
              );
            }),
          ),
        ),
      ],
    );
  }
}

// ── Job list with date-group headers ─────────────────────────────────────────

class _JobList extends StatelessWidget {
  final Future<List<Job>>? future;
  final _Sort sort;
  final VoidCallback onRefresh;
  final VoidCallback onJobStatusChanged;

  const _JobList({
    required this.future,
    required this.sort,
    required this.onRefresh,
    required this.onJobStatusChanged,
  });

  @override
  Widget build(BuildContext context) {
    if (future == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return FutureBuilder<List<Job>>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text('Error: ${snap.error}',
                  textAlign: TextAlign.center),
            ),
          );
        }

        final raw = snap.data ?? [];
        final jobs = _sorted(raw);

        if (jobs.isEmpty) {
          return RefreshIndicator(
            onRefresh: () async => onRefresh(),
            child: ListView(children: const [
              SizedBox(height: 120),
              Center(child: Text('No jobs found')),
            ]),
          );
        }

        // Build list items with date-group headers
        final items = _buildItems(jobs);

        return RefreshIndicator(
          onRefresh: () async => onRefresh(),
          child: ListView.builder(
            itemCount: items.length,
            itemBuilder: (_, i) {
              final item = items[i];
              if (item is String) {
                return _GroupHeader(label: item);
              }
              final job = item as Job;
              return GestureDetector(
                onTap: () async {
                  await Navigator.push(
                    context,
                    MaterialPageRoute(
                        builder: (_) => JobDetailScreen(job: job)),
                  );
                  onJobStatusChanged();
                },
                child: JobCard(job: job),
              );
            },
          ),
        );
      },
    );
  }

  List<Job> _sorted(List<Job> jobs) {
    final sorted = List<Job>.from(jobs);
    switch (sort) {
      case _Sort.date:
        sorted.sort((a, b) => _dateDesc(a, b));
      case _Sort.newFirst:
        // Unscored jobs first (newest), then scored by score desc, then date
        sorted.sort((a, b) {
          final aScored = a.llmScore != null;
          final bScored = b.llmScore != null;
          if (!aScored && bScored) return -1;
          if (aScored && !bScored) return 1;
          if (aScored && bScored) {
            final sc = b.llmScore!.compareTo(a.llmScore!);
            if (sc != 0) return sc;
          }
          return _dateDesc(a, b);
        });
      case _Sort.score:
        sorted.sort((a, b) {
          final aScore = a.llmScore ?? -1;
          final bScore = b.llmScore ?? -1;
          final sc = bScore.compareTo(aScore);
          if (sc != 0) return sc;
          return _dateDesc(a, b);
        });
    }
    return sorted;
  }

  int _dateDesc(Job a, Job b) {
    final da = a.dateCollected ?? a.datePosted ?? DateTime(2000);
    final db2 = b.dateCollected ?? b.datePosted ?? DateTime(2000);
    return db2.compareTo(da);
  }

  /// Returns a mixed list of String (group header) and Job items.
  List<Object> _buildItems(List<Job> jobs) {
    // For score-sorted tabs, skip date grouping
    if (sort == _Sort.score) return jobs;

    final now = DateTime.now();
    final today     = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));
    final weekStart = today.subtract(Duration(days: today.weekday - 1));

    final items = <Object>[];
    String? lastGroup;

    for (final job in jobs) {
      final d = job.dateCollected ?? job.datePosted;
      final group = _groupLabel(d, today, yesterday, weekStart);
      if (group != lastGroup) {
        items.add(group);
        lastGroup = group;
      }
      items.add(job);
    }
    return items;
  }

  String _groupLabel(DateTime? d, DateTime today, DateTime yesterday,
      DateTime weekStart) {
    if (d == null) return 'Older';
    final day = DateTime(d.year, d.month, d.day);
    if (!day.isBefore(today)) return 'Today';
    if (!day.isBefore(yesterday)) return 'Yesterday';
    if (!day.isBefore(weekStart)) return 'This Week';
    return 'Older';
  }
}

// ── Group header widget ───────────────────────────────────────────────────────

class _GroupHeader extends StatelessWidget {
  final String label;
  const _GroupHeader({required this.label});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelLarge?.copyWith(
              color: Colors.grey.shade600,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
            ),
      ),
    );
  }
}

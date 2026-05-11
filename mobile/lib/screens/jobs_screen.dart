import 'package:flutter/material.dart';
import '../models/job.dart';
import '../services/supabase_service.dart';
import '../widgets/job_card.dart';
import 'job_detail_screen.dart';

class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key});

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen>
    with SingleTickerProviderStateMixin {
  static const _tabs = [
    ('All', null),
    ('New', 'new'),
    ('Applied', 'applied'),
    ('Saved', 'saved'),
  ];

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

  void _ensureLoaded(int idx) {
    if (_futures[idx] == null) {
      setState(() {
        _futures[idx] =
            SupabaseService.listJobs(status: _tabs[idx].$2);
      });
    }
  }

  void _refreshTab(int idx) {
    setState(() {
      _futures[idx] = SupabaseService.listJobs(status: _tabs[idx].$2);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        TabBar(
          controller: _tabCtrl,
          tabs: _tabs.map((t) => Tab(text: t.$1)).toList(),
        ),
        Expanded(
          child: TabBarView(
            controller: _tabCtrl,
            children: List.generate(_tabs.length, (i) {
              return _JobList(
                future: _futures[i],
                onRefresh: () => _refreshTab(i),
                onJobStatusChanged: () => _invalidateAll(),
              );
            }),
          ),
        ),
      ],
    );
  }

  void _invalidateAll() {
    setState(() {
      for (int i = 0; i < _futures.length; i++) {
        _futures[i] = SupabaseService.listJobs(status: _tabs[i].$2);
      }
    });
  }
}

class _JobList extends StatelessWidget {
  final Future<List<Job>>? future;
  final VoidCallback onRefresh;
  final VoidCallback onJobStatusChanged;

  const _JobList({
    required this.future,
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
          return Center(child: Text('Error: ${snap.error}'));
        }
        final jobs = snap.data ?? [];
        if (jobs.isEmpty) {
          return RefreshIndicator(
            onRefresh: () async => onRefresh(),
            child: ListView(
              children: const [
                SizedBox(height: 120),
                Center(child: Text('No jobs found')),
              ],
            ),
          );
        }
        return RefreshIndicator(
          onRefresh: () async => onRefresh(),
          child: ListView.builder(
            itemCount: jobs.length,
            itemBuilder: (_, i) => GestureDetector(
              onTap: () async {
                await Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => JobDetailScreen(job: jobs[i]),
                  ),
                );
                onJobStatusChanged();
              },
              child: JobCard(job: jobs[i]),
            ),
          ),
        );
      },
    );
  }
}

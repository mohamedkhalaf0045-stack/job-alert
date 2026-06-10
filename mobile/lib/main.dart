import 'package:flutter/material.dart';
import 'screens/dashboard_screen.dart';
import 'screens/jobs_screen.dart';
import 'screens/settings_screen.dart';
import 'services/notification_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // SECURITY: the GitHub PAT comes from compile-time --dart-define only
  // (see build-apk.yml). It is never loaded from Supabase — bot_state is
  // readable with the public anon key, so a token stored there is public.
  runApp(const JobAlertApp());
}

class JobAlertApp extends StatelessWidget {
  const JobAlertApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Job Alert',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: Colors.blue,
        useMaterial3: true,
      ),
      home: const _Shell(),
    );
  }
}

class _Shell extends StatefulWidget {
  const _Shell();

  @override
  State<_Shell> createState() => _ShellState();
}

class _ShellState extends State<_Shell> {
  int _idx = 0;

  static const _titles = ['Cloud', 'Jobs', 'Settings'];

  @override
  void initState() {
    super.initState();
    NotificationService.init(
      onUpdateTap: () {
        if (mounted) setState(() => _idx = 0);
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_idx]),
        centerTitle: true,
      ),
      body: IndexedStack(
        index: _idx,
        children: const [
          DashboardScreen(),
          JobsScreen(),
          SettingsScreen(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _idx,
        onDestinationSelected: (i) => setState(() => _idx = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.cloud_outlined),
            selectedIcon: Icon(Icons.cloud),
            label: 'Cloud',
          ),
          NavigationDestination(
            icon: Icon(Icons.work_outline),
            selectedIcon: Icon(Icons.work),
            label: 'Jobs',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}

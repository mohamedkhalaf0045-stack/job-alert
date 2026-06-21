import 'dart:async';
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'config.dart';
import 'screens/dashboard_screen.dart';
import 'screens/jobs_screen.dart';
import 'screens/login_screen.dart';
import 'screens/onboarding_screen.dart';
import 'screens/settings_screen.dart';
import 'services/notification_service.dart';
import 'services/supabase_service.dart';

// Design tokens from nexu-io/open-design — Linear system
// Accent: Linear indigo #5E6AD2
const kAccent      = Color(0xFF5E6AD2);
const kAccentLight = Color(0xFF8A8FFF);
const kBg          = Color(0xFFFAFAFA);
const kSurface     = Color(0xFFFFFFFF);
const kFg          = Color(0xFF0F172A);
const kFg2         = Color(0xFF334155);
const kMuted       = Color(0xFF64748B);
const kMeta        = Color(0xFF94A3B8);
const kBorder      = Color(0xFFE2E8F0);
const kBorderSoft  = Color(0xFFF1F5F9);
const kSuccess     = Color(0xFF16A34A);
const kWarn        = Color(0xFFD97706);
const kDanger      = Color(0xFFDC2626);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // ignore: deprecated_member_use
  await Supabase.initialize(url: Config.supabaseUrl, anonKey: Config.supabaseKey);
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
      title: 'Job Alert UAE',
      debugShowCheckedModeBanner: false,
      theme: _theme(),
      home: const _AuthGate(),
    );
  }

  static ThemeData _theme() {
    const scheme = ColorScheme.light(
      primary:                 kAccent,
      onPrimary:               kSurface,
      primaryContainer:        Color(0x1A5E6AD2),
      onPrimaryContainer:      kAccent,
      secondary:               kAccentLight,
      onSecondary:             kSurface,
      surface:                 kSurface,
      onSurface:               kFg,
      onSurfaceVariant:        kFg2,
      surfaceContainerHighest: kBg,
      surfaceContainerLow:     kBorderSoft,
      outline:                 kBorder,
      outlineVariant:          kBorderSoft,
      error:                   kDanger,
      onError:                 kSurface,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: kBg,

      // AppBar
      appBarTheme: const AppBarTheme(
        backgroundColor: kSurface,
        foregroundColor: kFg,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 1,
        shadowColor: kBorder,
        titleTextStyle: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: kFg,
          letterSpacing: -0.3,
        ),
        centerTitle: true,
      ),

      // Bottom nav
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: kSurface,
        indicatorColor: Color(0x1A5E6AD2),
        height: 60,
        elevation: 0,
        shadowColor: kBorder,
        iconTheme: WidgetStatePropertyAll(
          IconThemeData(color: kMuted, size: 22),
        ),
        labelTextStyle: WidgetStatePropertyAll(
          TextStyle(fontSize: 11, fontWeight: FontWeight.w500, color: kMuted),
        ),
      ),

      // Tab bar
      tabBarTheme: const TabBarThemeData(
        labelColor: kAccent,
        unselectedLabelColor: kMuted,
        indicatorColor: kAccent,
        dividerColor: kBorder,
        indicatorSize: TabBarIndicatorSize.label,
        labelStyle: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        unselectedLabelStyle: TextStyle(fontSize: 13, fontWeight: FontWeight.w400),
        overlayColor: WidgetStatePropertyAll(Color(0x0A5E6AD2)),
      ),

      // Card
      cardTheme: CardThemeData(
        color: kSurface,
        elevation: 0,
        shadowColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: const BorderSide(color: kBorder),
        ),
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      ),

      // Divider
      dividerTheme: const DividerThemeData(color: kBorder, thickness: 1, space: 1),

      // Input
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: kSurface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: kBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: kBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: kAccent, width: 1.5),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        hintStyle: const TextStyle(color: kMeta, fontSize: 14),
      ),

      // Text
      textTheme: const TextTheme(
        headlineMedium: TextStyle(
          fontSize: 22, fontWeight: FontWeight.w700,
          color: kFg, letterSpacing: -0.5,
        ),
        titleLarge: TextStyle(
          fontSize: 18, fontWeight: FontWeight.w700,
          color: kFg, letterSpacing: -0.3,
        ),
        titleMedium: TextStyle(
          fontSize: 15, fontWeight: FontWeight.w600,
          color: kFg, letterSpacing: -0.2,
        ),
        titleSmall: TextStyle(
          fontSize: 13, fontWeight: FontWeight.w600,
          color: kFg, letterSpacing: -0.1,
        ),
        bodyLarge: TextStyle(
          fontSize: 15, color: kFg2, height: 1.5,
        ),
        bodyMedium: TextStyle(
          fontSize: 14, color: kFg2, height: 1.5,
        ),
        bodySmall: TextStyle(
          fontSize: 12, color: kMuted, height: 1.4,
        ),
        labelLarge: TextStyle(
          fontSize: 13, fontWeight: FontWeight.w600,
          color: kFg, letterSpacing: 0.1,
        ),
        labelMedium: TextStyle(
          fontSize: 12, fontWeight: FontWeight.w500, color: kMuted,
        ),
        labelSmall: TextStyle(
          fontSize: 11, fontWeight: FontWeight.w500, color: kMeta,
        ),
      ),

      // Chip
      chipTheme: ChipThemeData(
        backgroundColor: kBorderSoft,
        labelStyle: const TextStyle(fontSize: 12, color: kFg2),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
        side: const BorderSide(color: kBorder),
      ),

      // Progress
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: kAccent,
        linearTrackColor: kBorderSoft,
      ),
    );
  }
}

class _AuthGate extends StatelessWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<AuthState>(
      stream: Supabase.instance.client.auth.onAuthStateChange,
      builder: (context, snapshot) {
        final session = Supabase.instance.client.auth.currentSession;
        if (session != null) return const _PrefsGate();
        return const LoginScreen();
      },
    );
  }
}

// Checks whether the signed-in user has set up their preferences.
// If not, shows OnboardingScreen; otherwise shows _Shell.
class _PrefsGate extends StatefulWidget {
  const _PrefsGate();

  @override
  State<_PrefsGate> createState() => _PrefsGateState();
}

class _PrefsGateState extends State<_PrefsGate> {
  bool? _hasPrefs; // null = loading

  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    final prefs    = await SupabaseService.getUserPreferences();
    final keywords = prefs['keywords'] as List?;
    if (mounted) setState(() => _hasPrefs = keywords != null && keywords.isNotEmpty);
  }

  @override
  Widget build(BuildContext context) {
    if (_hasPrefs == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_hasPrefs == true) return const _Shell();
    return OnboardingScreen(onComplete: _check);
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

  Timer? _notifyDebounce;
  RealtimeChannel? _jobsChannel;

  @override
  void initState() {
    super.initState();
    NotificationService.init(
      onUpdateTap: () {
        if (mounted) setState(() => _idx = 0);
      },
      onJobTap: () {
        if (mounted) setState(() => _idx = 1);
      },
    );
    _subscribeToNewJobs();
  }

  void _subscribeToNewJobs() {
    _jobsChannel = Supabase.instance.client
        .channel('jobs_new_inserts')
        .onPostgresChanges(
          event: PostgresChangeEvent.insert,
          schema: 'public',
          table: 'jobs',
          callback: (_) {
            _notifyDebounce?.cancel();
            _notifyDebounce = Timer(const Duration(seconds: 5), () {
              NotificationService.showNewJob(
                  'New jobs may match your keywords — check your feed.');
            });
          },
        )
        .subscribe();
  }

  @override
  void dispose() {
    _notifyDebounce?.cancel();
    _jobsChannel?.unsubscribe();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_idx]),
        leading: Padding(
          padding: const EdgeInsets.only(left: 14),
          child: Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: kAccent,
              borderRadius: BorderRadius.circular(6),
            ),
            alignment: Alignment.center,
            child: const Text(
              'J',
              style: TextStyle(
                color: Colors.white,
                fontSize: 14,
                fontWeight: FontWeight.w700,
                height: 1,
              ),
            ),
          ),
        ),
        leadingWidth: 52,
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: kBorder),
        ),
      ),
      body: IndexedStack(
        index: _idx,
        children: const [
          DashboardScreen(),
          JobsScreen(),
          SettingsScreen(),
        ],
      ),
      bottomNavigationBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(height: 1, color: kBorder),
          NavigationBar(
            selectedIndex: _idx,
            onDestinationSelected: (i) => setState(() => _idx = i),
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.cloud_outlined),
                selectedIcon: Icon(Icons.cloud, color: kAccent),
                label: 'Cloud',
              ),
              NavigationDestination(
                icon: Icon(Icons.work_outline),
                selectedIcon: Icon(Icons.work, color: kAccent),
                label: 'Jobs',
              ),
              NavigationDestination(
                icon: Icon(Icons.settings_outlined),
                selectedIcon: Icon(Icons.settings, color: kAccent),
                label: 'Settings',
              ),
            ],
          ),
        ],
      ),
    );
  }
}

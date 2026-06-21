import 'dart:async';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'config.dart';
import 'screens/chat_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/jobs_screen.dart';
import 'screens/login_screen.dart';
import 'screens/onboarding_screen.dart';
import 'screens/settings_screen.dart';
import 'services/notification_service.dart';
import 'services/supabase_service.dart';

// Maximum individual job notifications to fire in one burst.
// If more arrive within the accumulation window, the rest become a
// single "+N more" summary so the drawer doesn't get flooded.
const _kMaxIndividualNotifs = 3;

// How long to wait after the last insert before draining the queue.
// The worker inserts jobs one-by-one; a 4-second window batches a
// typical scraper run into one flush.
const _kAccumulationWindow = Duration(seconds: 4);

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

// Handles FCM messages that arrive while the app is terminated.
// Must be a top-level function (not a closure or method).
@pragma('vm:entry-point')
Future<void> _fcmBackgroundHandler(RemoteMessage message) async {
  // Firebase is already initialised by the OS before this is called.
  // flutter_local_notifications is NOT available here; FCM shows the
  // system tray notification automatically from the notification payload.
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();
  FirebaseMessaging.onBackgroundMessage(_fcmBackgroundHandler);
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

class _ShellState extends State<_Shell> with WidgetsBindingObserver {
  int _idx = 0;

  static const _titles = ['Cloud', 'Jobs', 'Chat', 'Settings'];
  static const _kLastSeenKey = 'last_seen_jobs_ts';
  Key _chatKey = UniqueKey();

  RealtimeChannel? _jobsChannel;

  // User keywords (lowercase) — loaded once; used to filter realtime inserts.
  List<String> _userKeywords = [];

  // Pending inserts waiting for the accumulation window to close.
  final List<Map<String, dynamic>> _pendingJobs = [];
  Timer? _drainTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    NotificationService.init(
      onUpdateTap: () { if (mounted) setState(() => _idx = 0); },
      onJobTap:    () { if (mounted) setState(() => _idx = 1); },
    );
    _loadKeywords().then((_) => _catchUpNotifications());
    _subscribeToNewJobs();
    _initFcm();
  }

  // Register device with FCM so the server can push notifications when app is closed.
  Future<void> _initFcm() async {
    try {
      final messaging = FirebaseMessaging.instance;
      final settings  = await messaging.requestPermission(alert: true, badge: true, sound: true);
      if (settings.authorizationStatus == AuthorizationStatus.denied) return;

      final token = await messaging.getToken();
      if (token != null) {
        await SupabaseService.saveFcmToken(token);
      }

      // Refresh token when FCM rotates it.
      messaging.onTokenRefresh.listen((newToken) {
        SupabaseService.saveFcmToken(newToken);
      });

      // Foreground messages: FCM doesn't auto-show them on Android — show via local notification.
      FirebaseMessaging.onMessage.listen((msg) {
        final n = msg.notification;
        if (n == null || !mounted) return;
        NotificationService.showJobAlert(
          notifId:  msg.hashCode & 0x7FFFFFFF,
          title:    n.title ?? 'New job',
          company:  msg.data['company'] ?? '',
          location: msg.data['location'] ?? '',
          jobId:    msg.data['job_id'] ?? '',
        );
      });
    } catch (_) {
      // FCM setup is best-effort — don't crash if Firebase not configured yet.
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _catchUpNotifications();
    }
  }

  // Queries for jobs that arrived while the app was closed and notifies.
  Future<void> _catchUpNotifications() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final lastSeenMs = prefs.getInt(_kLastSeenKey);
      final since = lastSeenMs != null
          ? DateTime.fromMillisecondsSinceEpoch(lastSeenMs, isUtc: true)
          : DateTime.now().toUtc().subtract(const Duration(hours: 2));

      final now = DateTime.now().toUtc();
      await prefs.setInt(_kLastSeenKey, now.millisecondsSinceEpoch);

      if (_userKeywords.isEmpty) return;

      final missed = await SupabaseService.getNewJobsSince(since, _userKeywords);
      if (missed.isEmpty || !mounted) return;

      final toShow = missed.take(_kMaxIndividualNotifs).toList();
      final extra  = missed.length - toShow.length;

      for (int i = 0; i < toShow.length; i++) {
        final job      = toShow[i];
        final jobTitle = (job['title']    as String? ?? 'New job').trim();
        final company  = (job['company']  as String? ?? '').trim();
        final location = (job['location'] as String? ?? '').trim();
        final jobId    = (job['job_id']   as String? ?? '').trim();
        final notifId  = jobId.isNotEmpty
            ? (jobId.hashCode & 0x7FFFFFFF) + 3000
            : (4000 + i);

        await NotificationService.showJobAlert(
          notifId:  notifId,
          title:    jobTitle,
          company:  company,
          location: location,
          jobId:    jobId,
        );
        if (i < toShow.length - 1) {
          await Future.delayed(const Duration(milliseconds: 350));
        }
      }

      if (extra > 0) {
        await Future.delayed(const Duration(milliseconds: 350));
        await NotificationService.showNewJob(
          '$extra more missed job${extra == 1 ? '' : 's'} matching your keywords.',
        );
      }
    } catch (_) {
      // Catch-up is best-effort; never crash the app.
    }
  }

  // Load the user's keywords so we only notify for relevant jobs.
  Future<void> _loadKeywords() async {
    final prefs = await SupabaseService.getUserPreferences();
    final kws = (prefs['keywords'] as List?)?.cast<String>() ?? [];
    if (mounted) {
      setState(() {
        _userKeywords = kws.map((k) => k.toLowerCase()).toList();
      });
    }
  }

  void _subscribeToNewJobs() {
    _jobsChannel = Supabase.instance.client
        .channel('jobs_new_inserts')
        .onPostgresChanges(
          event: PostgresChangeEvent.insert,
          schema: 'public',
          table: 'jobs',
          callback: _onJobInserted,
        )
        .subscribe();
  }

  void _onJobInserted(PostgresChangePayload payload) {
    final rec = payload.newRecord;
    // Empty newRecord means REPLICA IDENTITY isn't FULL — skip silently.
    if (rec.isEmpty) return;

    final title = (rec['title'] as String? ?? '').toLowerCase();

    // Filter by keywords only when loaded; pass everything through while loading.
    if (_userKeywords.isNotEmpty) {
      final matches = _userKeywords.any((kw) => title.contains(kw));
      if (!matches) return;
    }

    _pendingJobs.add(rec);

    // Reset the drain timer on every new insert so we accumulate rapid bursts.
    _drainTimer?.cancel();
    _drainTimer = Timer(_kAccumulationWindow, _drainNotifications);
  }

  Future<void> _drainNotifications() async {
    if (!mounted || _pendingJobs.isEmpty) return;

    final jobs = List<Map<String, dynamic>>.from(_pendingJobs);
    _pendingJobs.clear();

    final toShow = jobs.take(_kMaxIndividualNotifs).toList();
    final extra  = jobs.length - toShow.length;

    for (int i = 0; i < toShow.length; i++) {
      final job      = toShow[i];
      final jobTitle = (job['title']    as String? ?? 'New job').trim();
      final company  = (job['company']  as String? ?? '').trim();
      final location = (job['location'] as String? ?? '').trim();
      final jobId    = (job['job_id']   as String? ?? '').trim();

      // Use the job_id hash as notification ID so each job gets its own slot
      // in the status bar instead of replacing the previous one.
      final notifId = jobId.isNotEmpty
          ? (jobId.hashCode & 0x7FFFFFFF) + 1000
          : (2000 + i);

      await NotificationService.showJobAlert(
        notifId:  notifId,
        title:    jobTitle,
        company:  company,
        location: location,
        jobId:    jobId,
      );

      // Small gap so Android doesn't coalesce rapid notifications.
      if (i < toShow.length - 1) {
        await Future.delayed(const Duration(milliseconds: 350));
      }
    }

    if (extra > 0) {
      await Future.delayed(const Duration(milliseconds: 350));
      await NotificationService.showNewJob(
        '$extra more new job${extra == 1 ? '' : 's'} matching your keywords.',
      );
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _drainTimer?.cancel();
    _jobsChannel?.unsubscribe();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_idx]),
        actions: _idx == 2
            ? [
                IconButton(
                  icon: const Icon(Icons.delete_outline),
                  tooltip: 'Clear chat',
                  onPressed: () {
                    final state = context
                        .findAncestorStateOfType<_ShellState>();
                    // Rebuild chat screen with a new key to reset state
                    setState(() => _chatKey = UniqueKey());
                  },
                ),
              ]
            : null,
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
        children: [
          const DashboardScreen(),
          const JobsScreen(),
          ChatScreen(key: _chatKey),
          const SettingsScreen(),
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
                icon: Icon(Icons.chat_bubble_outline),
                selectedIcon: Icon(Icons.chat_bubble, color: kAccent),
                label: 'Chat',
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

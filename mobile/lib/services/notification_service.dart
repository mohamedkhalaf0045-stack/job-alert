import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  static final _plugin = FlutterLocalNotificationsPlugin();

  static Function()? _onUpdateTap;
  static Function()? _onJobTap;

  // ── Init ─────────────────────────────────────────────────────────────────

  static Future<void> init({
    Function()? onUpdateTap,
    Function()? onJobTap,
  }) async {
    _onUpdateTap = onUpdateTap;
    _onJobTap    = onJobTap;

    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidInit);

    await _plugin.initialize(
      initSettings,
      onDidReceiveNotificationResponse: (details) {
        final payload = details.payload ?? '';
        if (payload == 'update') {
          _onUpdateTap?.call();
        } else {
          // 'jobs' generic tap OR 'job:<id>' specific tap — both open Jobs tab
          _onJobTap?.call();
        }
      },
    );

    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
  }

  // ── Per-job notification ──────────────────────────────────────────────────

  /// Shows a single job-specific notification.
  /// [notifId] must be unique per job to avoid replacing other notifications.
  static Future<void> showJobAlert({
    required int notifId,
    required String title,
    required String company,
    required String location,
    required String jobId,
  }) async {
    final subtitle = [
      if (company.isNotEmpty) company,
      if (location.isNotEmpty) location,
    ].join(' · ');

    const channel = AndroidNotificationDetails(
      'job_alerts',
      'Job Alerts',
      channelDescription: 'New job matches for your keywords',
      importance: Importance.high,
      priority: Priority.high,
      icon: '@mipmap/ic_launcher',
    );

    await _plugin.show(
      notifId,
      title,
      subtitle.isNotEmpty ? subtitle : 'New job found',
      const NotificationDetails(android: channel),
      payload: 'job:$jobId',
    );
  }

  // ── Summary notification (used when a burst has many jobs) ────────────────

  static Future<void> showNewJob(String summary) async {
    const channel = AndroidNotificationDetails(
      'job_alerts',
      'Job Alerts',
      channelDescription: 'New job matches for your keywords',
      importance: Importance.high,
      priority: Priority.high,
      icon: '@mipmap/ic_launcher',
    );
    await _plugin.show(
      2,
      'New jobs found',
      summary,
      const NotificationDetails(android: channel),
      payload: 'jobs',
    );
  }

  // ── Update notification ───────────────────────────────────────────────────

  static Future<void> showUpdateAvailable(String versionName) async {
    const channel = AndroidNotificationDetails(
      'update_channel',
      'App Updates',
      channelDescription: 'Notifications about new app versions',
      importance: Importance.high,
      priority: Priority.high,
      icon: '@mipmap/ic_launcher',
      ticker: 'Update available',
    );
    await _plugin.show(
      1,
      'Update available — $versionName',
      'Tap to download and install the latest version.',
      const NotificationDetails(android: channel),
      payload: 'update',
    );
  }
}

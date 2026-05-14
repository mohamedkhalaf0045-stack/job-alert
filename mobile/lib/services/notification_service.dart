import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  static final _plugin = FlutterLocalNotificationsPlugin();

  static Function()? _onUpdateTap;

  static Future<void> init({Function()? onUpdateTap}) async {
    _onUpdateTap = onUpdateTap;

    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidInit);

    await _plugin.initialize(
      initSettings,
      onDidReceiveNotificationResponse: (details) {
        if (details.payload == 'update') {
          _onUpdateTap?.call();
        }
      },
    );

    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.requestNotificationsPermission();
  }

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

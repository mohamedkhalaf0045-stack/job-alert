import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'supabase_service.dart';

class UpdateInfo {
  final String versionName;
  final int versionCode;
  final String apkUrl;

  const UpdateInfo({
    required this.versionName,
    required this.versionCode,
    required this.apkUrl,
  });
}

class UpdateService {
  /// Returns [UpdateInfo] if a newer version is available, null otherwise.
  static Future<UpdateInfo?> checkForUpdate() async {
    try {
      final info    = await PackageInfo.fromPlatform();
      final current = int.tryParse(info.buildNumber) ?? 0;

      final latestCode = int.tryParse(
              await SupabaseService.getConfigValue('update_version_code', '0')) ??
          0;
      final latestName =
          await SupabaseService.getConfigValue('update_version_name', '');
      final apkUrl =
          await SupabaseService.getConfigValue('update_apk_url', '');

      if (latestCode > current && apkUrl.isNotEmpty) {
        return UpdateInfo(
          versionName: latestName.isNotEmpty ? latestName : 'v$latestCode',
          versionCode: latestCode,
          apkUrl: apkUrl,
        );
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  /// Downloads the APK from [url] and launches the Android installer.
  /// [onProgress] receives 0.0–1.0 as download progresses.
  static Future<String?> downloadAndInstall(
    String url,
    void Function(double) onProgress,
  ) async {
    try {
      final dir      = await getTemporaryDirectory();
      final filePath = '${dir.path}/job-alert-update.apk';

      final request  = http.Request('GET', Uri.parse(url));
      final response = await request.send();
      final total    = response.contentLength ?? 0;

      final sink   = File(filePath).openWrite();
      int received = 0;

      await for (final chunk in response.stream) {
        sink.add(chunk);
        received += chunk.length;
        if (total > 0) onProgress(received / total);
      }
      await sink.close();

      final result = await OpenFilex.open(filePath);
      if (result.type != ResultType.done) {
        return 'Could not open installer: ${result.message}';
      }
      return null; // success
    } catch (e) {
      return e.toString();
    }
  }
}

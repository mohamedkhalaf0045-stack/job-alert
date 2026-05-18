import 'dart:convert';
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
  static const _owner = 'mohamedkhalaf0045-stack';
  static const _repo  = 'job-alert';

  /// Checks GitHub Releases first, then falls back to Supabase/Google Drive.
  static Future<UpdateInfo?> checkForUpdate() async {
    return await _checkGitHub() ?? await _checkSupabase();
  }

  static Future<UpdateInfo?> _checkGitHub() async {
    try {
      final info = await PackageInfo.fromPlatform();
      final r = await http
          .get(
            Uri.parse(
                'https://api.github.com/repos/$_owner/$_repo/releases/latest'),
            headers: {'Accept': 'application/vnd.github+json'},
          )
          .timeout(const Duration(seconds: 10));
      if (r.statusCode != 200) return null;

      final body   = jsonDecode(r.body) as Map<String, dynamic>;
      final rawTag = (body['tag_name'] as String? ?? '').replaceFirst('v', '');
      // Normalize both sides to major.minor.patch so "1.0.4-dev" == "1.0.4"
      final tag = rawTag.split(RegExp(r'[-+]')).first;
      if (tag.isEmpty || tag == info.version) return null;

      // Prefer arm64-v8a (covers all modern phones), then armeabi-v7a
      final assets = (body['assets'] as List? ?? []).cast<Map<String, dynamic>>();
      String? url;
      for (final abi in ['arm64-v8a', 'armeabi-v7a', 'x86_64']) {
        final match = assets.where(
          (a) => (a['name'] as String? ?? '').contains(abi),
        );
        if (match.isNotEmpty) {
          url = match.first['browser_download_url'] as String?;
          break;
        }
      }
      if (url == null) return null;

      return UpdateInfo(versionName: tag, versionCode: 0, apkUrl: url);
    } catch (_) {
      return null;
    }
  }

  static Future<UpdateInfo?> _checkSupabase() async {
    try {
      final info       = await PackageInfo.fromPlatform();
      final current    = int.tryParse(info.buildNumber) ?? 0;
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
      return null;
    } catch (e) {
      return e.toString();
    }
  }
}

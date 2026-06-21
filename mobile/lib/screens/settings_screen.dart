import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../models/app_settings.dart';
import '../services/supabase_service.dart';
import '../services/github_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _formKey = GlobalKey<FormState>();

  final _keywordsCtrl    = TextEditingController();
  final _locationCtrl    = TextEditingController();
  final _maxHoursCtrl    = TextEditingController();
  final _excludeCtrl     = TextEditingController();
  final _cookieCtrl      = TextEditingController();
  final _profileCtrl     = TextEditingController();
  final _minScoreCtrl    = TextEditingController();
  final _ollamaCtrl      = TextEditingController();
  final _timezoneCtrl    = TextEditingController();
  final _updateUrlCtrl   = TextEditingController();
  final _updateVerCtrl   = TextEditingController();
  final _updateCodeCtrl  = TextEditingController();
  final _gmailEmailCtrl  = TextEditingController();
  final _gmailPassCtrl   = TextEditingController();
  final _ghTokenCtrl     = TextEditingController();
  String _currentVersion = '';

  bool _searchLinkedIn = true;
  bool _searchIndeed   = true;
  bool _searchGmail    = false;
  bool _showCookie     = false;
  bool _showGmailPass  = false;
  bool _showGhToken    = false;
  bool _loading        = true;
  bool _saving         = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _keywordsCtrl.dispose();
    _locationCtrl.dispose();
    _maxHoursCtrl.dispose();
    _excludeCtrl.dispose();
    _cookieCtrl.dispose();
    _profileCtrl.dispose();
    _minScoreCtrl.dispose();
    _ollamaCtrl.dispose();
    _timezoneCtrl.dispose();
    _updateUrlCtrl.dispose();
    _updateVerCtrl.dispose();
    _updateCodeCtrl.dispose();
    _gmailEmailCtrl.dispose();
    _gmailPassCtrl.dispose();
    _ghTokenCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final results = await Future.wait([
        PackageInfo.fromPlatform(),
        SupabaseService.getSettings(),
        SupabaseService.getConfigValue('update_apk_url', ''),
        SupabaseService.getConfigValue('update_version_name', ''),
        SupabaseService.getConfigValue('update_version_code', ''),
        SupabaseService.getUserPreferences(),
      ]);
      final info  = results[0] as PackageInfo;
      final s     = results[1] as AppSettings;
      final url   = results[2] as String;
      final ver   = results[3] as String;
      final code  = results[4] as String;
      final prefs = results[5] as Map<String, dynamic>;

      if (mounted) {
        setState(() {
          // Keywords / locations / excludes / minScore come from user_preferences
          // when available (they are the source of truth for the per-user feed).
          // Fall back to legacy bot_state values for first-time setup.
          final prefKw   = (prefs['keywords']        as List?)?.cast<String>();
          final prefLoc  = (prefs['locations']       as List?)?.cast<String>();
          final prefExcl = (prefs['exclude_keywords'] as List?)?.cast<String>();
          final prefMin  = prefs['min_score'] as int?;

          _keywordsCtrl.text = prefKw != null && prefKw.isNotEmpty
              ? prefKw.join(', ')
              : s.keywords.join(', ');
          _locationCtrl.text = prefLoc != null && prefLoc.isNotEmpty
              ? prefLoc.join(', ')
              : s.location;
          _excludeCtrl.text  = prefExcl != null && prefExcl.isNotEmpty
              ? prefExcl.join(', ')
              : s.excludeKeywords;
          _minScoreCtrl.text = (prefMin ?? s.minAiScore).toString();

          _maxHoursCtrl.text   = s.maxHours.toString();
          _cookieCtrl.text     = s.linkedInCookie;
          _profileCtrl.text    = s.userProfile;
          _ollamaCtrl.text     = s.ollamaUrl;
          _timezoneCtrl.text   = s.timezone;
          _searchLinkedIn      = s.searchLinkedIn;
          _searchIndeed        = s.searchIndeed;
          _searchGmail         = s.searchGmail;
          _gmailEmailCtrl.text = s.gmailEmail;
          _gmailPassCtrl.text  = s.gmailAppPassword;
          _ghTokenCtrl.text    = s.githubToken;
          _updateUrlCtrl.text  = url;
          _updateVerCtrl.text  = ver;
          _updateCodeCtrl.text = code;
          _currentVersion      = '${info.version}+${info.buildNumber}';
          _loading             = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _saving = true);

    final keywords = _keywordsCtrl.text
        .split(',')
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();

    final settings = AppSettings(
      keywords:           keywords,
      location:           _locationCtrl.text.trim(),
      maxHours:           int.tryParse(_maxHoursCtrl.text.trim()) ?? 24,
      searchLinkedIn:     _searchLinkedIn,
      searchIndeed:       _searchIndeed,
      excludeKeywords:    _excludeCtrl.text.trim(),
      linkedInCookie:     _cookieCtrl.text.trim(),
      userProfile:        _profileCtrl.text.trim(),
      minAiScore:         int.tryParse(_minScoreCtrl.text.trim()) ?? 4,
      ollamaUrl:          _ollamaCtrl.text.trim(),
      timezone:           _timezoneCtrl.text.trim().isEmpty
                              ? AppSettings.deviceTimezone()
                              : _timezoneCtrl.text.trim(),
      searchGmail:        _searchGmail,
      gmailEmail:         _gmailEmailCtrl.text.trim(),
      gmailAppPassword:   _gmailPassCtrl.text.trim(),
      githubToken:        _ghTokenCtrl.text.trim(),
    );

    // Update the in-memory token immediately so the Cloud tab picks it up
    // without needing an app restart.
    GitHubService.setToken(_ghTokenCtrl.text.trim());

    final excludeKw = _excludeCtrl.text
        .split(',')
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    final locations = _locationCtrl.text
        .split(',')
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    final minScore = int.tryParse(_minScoreCtrl.text.trim());

    final results = await Future.wait([
      SupabaseService.saveSettings(settings),
      SupabaseService.setConfigValue('update_apk_url',      _updateUrlCtrl.text.trim()),
      SupabaseService.setConfigValue('update_version_name', _updateVerCtrl.text.trim()),
      SupabaseService.setConfigValue('update_version_code', _updateCodeCtrl.text.trim()),
      SupabaseService.saveUserPreferences(
        keywords:        keywords,
        locations:       locations,
        excludeKeywords: excludeKw,
        minScore:        minScore,
      ),
    ]);
    final ok = results.every((r) => r == true);
    if (mounted) {
      setState(() => _saving = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(ok ? 'Settings saved.' : 'Save failed — check connection.'),
        backgroundColor: ok ? Colors.green : Colors.red,
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());

    return Form(
      key: _formKey,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _Section('Job Search'),
          TextFormField(
            controller: _keywordsCtrl,
            decoration: const InputDecoration(
              labelText: 'Keywords',
              hintText: 'IT Support, Helpdesk, Sysadmin',
              helperText: 'Comma-separated — each is searched separately',
            ),
            maxLines: 3,
            validator: (v) =>
                (v == null || v.trim().isEmpty) ? 'At least one keyword required' : null,
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _locationCtrl,
            decoration: const InputDecoration(
              labelText: 'Locations',
              hintText: 'United Arab Emirates, Egypt',
              helperText: 'Separate multiple locations with commas',
            ),
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _maxHoursCtrl,
            decoration: const InputDecoration(
              labelText: 'Max job age (hours)',
              hintText: '24',
            ),
            keyboardType: TextInputType.number,
            validator: (v) {
              if (v == null || v.trim().isEmpty) return null;
              if (int.tryParse(v.trim()) == null) return 'Must be a number';
              return null;
            },
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _excludeCtrl,
            decoration: const InputDecoration(
              labelText: 'Exclude keywords (optional)',
              hintText: 'senior, intern, agency',
              helperText: 'Comma-separated — jobs containing these are hidden',
            ),
          ),
          const SizedBox(height: 12),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: TextFormField(
                  controller: _timezoneCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Timezone',
                    hintText: 'UTC+4',
                    helperText: 'Used to display job times in your local time',
                  ),
                  validator: (v) {
                    if (v == null || v.trim().isEmpty) return null;
                    if (!RegExp(r'^UTC[+-]\d{1,2}(:\d{2})?$').hasMatch(v.trim())) {
                      return 'Format: UTC+4 or UTC-5';
                    }
                    return null;
                  },
                ),
              ),
              const SizedBox(width: 8),
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: OutlinedButton.icon(
                  onPressed: () => setState(
                    () => _timezoneCtrl.text = AppSettings.deviceTimezone(),
                  ),
                  icon: const Icon(Icons.my_location, size: 18),
                  label: const Text('Auto'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          _Section('Sources'),
          SwitchListTile(
            title: const Text('Search LinkedIn'),
            value: _searchLinkedIn,
            onChanged: (v) => setState(() => _searchLinkedIn = v),
          ),
          SwitchListTile(
            title: const Text('Search Indeed'),
            value: _searchIndeed,
            onChanged: (v) => setState(() => _searchIndeed = v),
          ),
          const SizedBox(height: 24),
          _Section('Authentication'),
          TextFormField(
            controller: _ghTokenCtrl,
            obscureText: !_showGhToken,
            decoration: InputDecoration(
              labelText: 'GitHub Personal Access Token',
              helperText: 'github.com → Settings → Developer settings → Personal access tokens → Fine-grained → Actions: Read & Write',
              suffixIcon: IconButton(
                icon: Icon(_showGhToken ? Icons.visibility_off : Icons.visibility),
                onPressed: () => setState(() => _showGhToken = !_showGhToken),
              ),
            ),
            maxLines: _showGhToken ? 2 : 1,
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _cookieCtrl,
            obscureText: !_showCookie,
            decoration: InputDecoration(
              labelText: 'LinkedIn Cookie (li_at=...)',
              helperText: 'Paste the full cookie string from your browser',
              suffixIcon: IconButton(
                icon: Icon(_showCookie ? Icons.visibility_off : Icons.visibility),
                onPressed: () => setState(() => _showCookie = !_showCookie),
              ),
            ),
            maxLines: _showCookie ? 3 : 1,
          ),
          const SizedBox(height: 24),
          _Section('Email Alerts'),
          SwitchListTile(
            title: const Text('Search Gmail for job alerts'),
            value: _searchGmail,
            onChanged: (v) => setState(() => _searchGmail = v),
          ),
          if (_searchGmail) ...[
            const SizedBox(height: 12),
            TextFormField(
              controller: _gmailEmailCtrl,
              enabled: _searchGmail,
              decoration: const InputDecoration(
                labelText: 'Gmail address',
                hintText: 'your.email@gmail.com',
              ),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _gmailPassCtrl,
              enabled: _searchGmail,
              obscureText: !_showGmailPass,
              decoration: InputDecoration(
                labelText: 'Gmail app password',
                helperText: 'Get app password: myaccount.google.com/apppasswords (requires 2FA)',
                suffixIcon: IconButton(
                  icon: Icon(_showGmailPass ? Icons.visibility_off : Icons.visibility),
                  onPressed: () => setState(() => _showGmailPass = !_showGmailPass),
                ),
              ),
              maxLines: _showGmailPass ? 2 : 1,
            ),
          ],
          const SizedBox(height: 24),
          _Section('AI Enrichment (Ollama)'),
          TextFormField(
            controller: _profileCtrl,
            decoration: const InputDecoration(
              labelText: 'Your profile',
              hintText: 'IT Support Engineer, 4 years UAE, Windows Server, AD...',
              helperText: 'Used by the local LLM to score job relevance',
            ),
            maxLines: 4,
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _minScoreCtrl,
            decoration: const InputDecoration(
              labelText: 'Min AI score (0–10)',
              hintText: '4',
              helperText: 'Jobs scoring below this are auto-dismissed',
            ),
            keyboardType: TextInputType.number,
            validator: (v) {
              if (v == null || v.trim().isEmpty) return null;
              final n = int.tryParse(v.trim());
              if (n == null || n < 0 || n > 10) return 'Must be 0–10';
              return null;
            },
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _ollamaCtrl,
            decoration: const InputDecoration(
              labelText: 'Ollama URL',
              hintText: 'http://localhost:11434',
              helperText: 'Change if enricher runs on another PC on your network',
            ),
          ),
          const SizedBox(height: 24),
          _Section('App Updates'),
          if (_currentVersion.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                'Installed: $_currentVersion',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: Colors.grey),
              ),
            ),
          TextFormField(
            controller: _updateUrlCtrl,
            decoration: const InputDecoration(
              labelText: 'APK download URL',
              hintText: 'https://drive.google.com/uc?export=download&id=...',
              helperText: 'Google Drive direct-download link to the latest APK',
            ),
          ),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextFormField(
                controller: _updateVerCtrl,
                decoration: const InputDecoration(
                  labelText: 'Latest version name',
                  hintText: '1.0.1',
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextFormField(
                controller: _updateCodeCtrl,
                decoration: const InputDecoration(
                  labelText: 'Version code',
                  hintText: '2',
                  helperText: 'Must be > installed code',
                ),
                keyboardType: TextInputType.number,
              ),
            ),
          ]),
          const SizedBox(height: 32),
          _saving
              ? const Center(child: CircularProgressIndicator())
              : FilledButton.icon(
                  onPressed: _save,
                  icon: const Icon(Icons.save),
                  label: const Text('Save Settings'),
                ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _load,
            icon: const Icon(Icons.refresh),
            label: const Text('Reload from Cloud'),
          ),
          const SizedBox(height: 32),
          const Card(
            child: Padding(
              padding: EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Note', style: TextStyle(fontWeight: FontWeight.bold)),
                  SizedBox(height: 4),
                  Text(
                    'Settings saved here are picked up by the cloud worker on its next run. '
                    'They override the GitHub Actions secrets.',
                    style: TextStyle(fontSize: 13),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 32),
          const Divider(),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _confirmLogout,
            icon: const Icon(Icons.logout, color: Colors.red),
            label: const Text('Sign Out', style: TextStyle(color: Colors.red)),
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(48),
              side: const BorderSide(color: Colors.red),
            ),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Future<void> _confirmLogout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will be returned to the login screen.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Sign Out'),
          ),
        ],
      ),
    );
    if (ok == true) {
      await Supabase.instance.client.auth.signOut();
      // _AuthGate reacts to onAuthStateChange and navigates to LoginScreen.
    }
  }
}

class _Section extends StatelessWidget {
  final String title;
  const _Section(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12, top: 8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          title,
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(
                color: Theme.of(context).colorScheme.primary,
                fontWeight: FontWeight.w600,
              ),
        ),
      ),
    );
  }
}

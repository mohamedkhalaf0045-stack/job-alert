class AppSettings {
  final List<String> keywords;
  final String location;
  final int maxHours;
  final bool searchLinkedIn;
  final bool searchIndeed;
  final String excludeKeywords;
  final String linkedInCookie;
  final String userProfile;
  final int minAiScore;
  final String ollamaUrl;
  final String timezone;
  final bool searchGmail;
  final String gmailEmail;
  final String gmailAppPassword;
  final String githubToken;

  const AppSettings({
    required this.keywords,
    required this.location,
    required this.maxHours,
    required this.searchLinkedIn,
    required this.searchIndeed,
    required this.excludeKeywords,
    required this.linkedInCookie,
    required this.userProfile,
    required this.minAiScore,
    required this.ollamaUrl,
    required this.timezone,
    required this.searchGmail,
    required this.gmailEmail,
    required this.gmailAppPassword,
    required this.githubToken,
  });

  factory AppSettings.defaults() => AppSettings(
        keywords: const [],
        location: '',
        maxHours: 24,
        searchLinkedIn: true,
        searchIndeed: true,
        excludeKeywords: '',
        linkedInCookie: '',
        userProfile: '',
        minAiScore: 4,
        ollamaUrl: 'http://localhost:11434',
        timezone: deviceTimezone(),
        searchGmail: false,
        gmailEmail: '',
        gmailAppPassword: '',
        githubToken: '',
      );

  static String deviceTimezone() {
    final offset = DateTime.now().timeZoneOffset;
    final h = offset.inMinutes ~/ 60;
    final m = offset.inMinutes.abs() % 60;
    final sign = h >= 0 ? '+' : '-';
    return m == 0 ? 'UTC$sign${h.abs()}' : 'UTC$sign${h.abs()}:${m.toString().padLeft(2, '0')}';
  }

  factory AppSettings.fromMap(Map<String, String> map) => AppSettings(
        keywords: (map['keywords'] ?? '')
            .split(',')
            .map((s) => s.trim())
            .where((s) => s.isNotEmpty)
            .toList(),
        location: map['location'] ?? '',
        maxHours: int.tryParse(map['max_hours'] ?? '') ?? 24,
        searchLinkedIn: (map['search_linkedin'] ?? 'true') != 'false',
        searchIndeed: (map['search_indeed'] ?? 'true') != 'false',
        excludeKeywords: map['exclude_keywords'] ?? '',
        linkedInCookie: map['linkedin_cookie'] ?? '',
        userProfile: map['user_profile'] ?? '',
        minAiScore: int.tryParse(map['llm_min_score'] ?? '') ?? 4,
        ollamaUrl: map['ollama_url'] ?? 'http://localhost:11434',
        timezone: map['timezone']?.isNotEmpty == true ? map['timezone']! : deviceTimezone(),
        searchGmail: (map['search_gmail'] ?? 'false') != 'false',
        gmailEmail: map['gmail_email'] ?? '',
        gmailAppPassword: map['gmail_app_password'] ?? '',
        githubToken: map['github_token'] ?? '',
      );

  Map<String, String> toMap() => {
        'keywords': keywords.join(','),
        'location': location,
        'max_hours': maxHours.toString(),
        'search_linkedin': searchLinkedIn.toString(),
        'search_indeed': searchIndeed.toString(),
        'exclude_keywords': excludeKeywords,
        'linkedin_cookie': linkedInCookie,
        'user_profile': userProfile,
        'llm_min_score': minAiScore.toString(),
        'ollama_url': ollamaUrl,
        'timezone': timezone,
        'search_gmail': searchGmail.toString(),
        'gmail_email': gmailEmail,
        'gmail_app_password': gmailAppPassword,
        'github_token': githubToken,
      };

  /// Parses the stored timezone string and returns its UTC offset in hours.
  /// e.g. "UTC+4 (UAE)" → 4, "UTC-5 (EST)" → -5, "UTC" → 0
  int get timezoneOffsetHours {
    final m = RegExp(r'UTC([+-]\d+)').firstMatch(timezone);
    if (m == null) return 0;
    return int.tryParse(m.group(1)!) ?? 0;
  }
}

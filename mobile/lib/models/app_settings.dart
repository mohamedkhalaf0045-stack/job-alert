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
  });

  factory AppSettings.defaults() => const AppSettings(
        keywords: [],
        location: '',
        maxHours: 24,
        searchLinkedIn: true,
        searchIndeed: true,
        excludeKeywords: '',
        linkedInCookie: '',
        userProfile: '',
        minAiScore: 4,
        ollamaUrl: 'http://localhost:11434',
      );

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
      };
}

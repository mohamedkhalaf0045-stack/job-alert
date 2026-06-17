class Job {
  final String jobId;
  final String title;
  final String company;
  final String location;
  final String url;
  final String source;
  final String status;
  final String? myStatus;
  final DateTime? datePosted;
  final DateTime? dateCollected;

  // Phase 2: multi-criteria scoring
  final int? llmScore;             // overall
  final String? llmSummary;        // reasoning sentence
  final int? skillsMatch;
  final int? experienceMatch;
  final int? locationMatch;
  final int? seniorityMatch;
  final List<String> matchedSkills;
  final List<String> missingSkills;
  final List<String> redFlags;

  // Phase 3: cross-source dedup
  final String? duplicateOfUrl;

  // Phase 5: auto cover letter draft
  final String? coverLetterDraft;

  const Job({
    required this.jobId,
    required this.title,
    required this.company,
    required this.location,
    required this.url,
    required this.source,
    required this.status,
    this.myStatus,
    this.datePosted,
    this.dateCollected,
    this.llmScore,
    this.llmSummary,
    this.skillsMatch,
    this.experienceMatch,
    this.locationMatch,
    this.seniorityMatch,
    this.matchedSkills = const [],
    this.missingSkills = const [],
    this.redFlags = const [],
    this.duplicateOfUrl,
    this.coverLetterDraft,
  });

  factory Job.fromJson(Map<String, dynamic> json) => Job(
        jobId:           json['job_id']    as String? ?? '',
        title:           json['title']     as String? ?? '',
        company:         json['company']   as String? ?? '',
        location:        json['location']  as String? ?? '',
        url:             json['url']       as String? ?? '',
        source:          json['source']    as String? ?? '',
        status:          json['status']    as String? ?? 'new',
        myStatus:        json['my_status'] as String?,
        datePosted:      _parseDate(json['date_posted']),
        dateCollected:   _parseDate(json['date_collected']),
        llmScore:        json['llm_score']   as int?,
        llmSummary:      json['llm_summary'] as String?,
        skillsMatch:     json['skills_match']     as int?,
        experienceMatch: json['experience_match'] as int?,
        locationMatch:   json['location_match']   as int?,
        seniorityMatch:  json['seniority_match']  as int?,
        matchedSkills:   _parseList(json['matched_skills']),
        missingSkills:   _parseList(json['missing_skills']),
        redFlags:        _parseList(json['red_flags']),
        duplicateOfUrl:  json['duplicate_of_url']  as String?,
        coverLetterDraft: json['cover_letter_draft'] as String?,
      );

  Job copyWith({String? status, String? myStatus}) => Job(
        jobId: jobId, title: title, company: company,
        location: location, url: url, source: source,
        status: status ?? this.status,
        myStatus: myStatus ?? this.myStatus,
        datePosted: datePosted, dateCollected: dateCollected,
        llmScore: llmScore, llmSummary: llmSummary,
        skillsMatch: skillsMatch, experienceMatch: experienceMatch,
        locationMatch: locationMatch, seniorityMatch: seniorityMatch,
        matchedSkills: matchedSkills, missingSkills: missingSkills,
        redFlags: redFlags,
        duplicateOfUrl: duplicateOfUrl,
        coverLetterDraft: coverLetterDraft,
      );

  /// True if Phase 2 multi-criteria data is available (vs legacy single-score).
  bool get hasBreakdown =>
      skillsMatch != null || experienceMatch != null ||
      locationMatch != null || seniorityMatch != null;

  bool get isDuplicate => (duplicateOfUrl ?? '').isNotEmpty;
  bool get hasCoverLetter => (coverLetterDraft ?? '').trim().isNotEmpty;

  static DateTime? _parseDate(dynamic v) {
    if (v == null) return null;
    try { return DateTime.parse(v as String); } catch (_) { return null; }
  }

  /// Supabase returns jsonb arrays as List<dynamic>. Defensive: also accepts
  /// a JSON-encoded string fallback (e.g. when the column was stored as text).
  static List<String> _parseList(dynamic v) {
    if (v == null) return const [];
    if (v is List) return v.map((e) => e?.toString() ?? '').where((s) => s.isNotEmpty).toList();
    if (v is String && v.trim().isNotEmpty) {
      // Best-effort: comma-split if it doesn't look like JSON
      return v.split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).toList();
    }
    return const [];
  }
}

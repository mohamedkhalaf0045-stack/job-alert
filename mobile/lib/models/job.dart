class Job {
  final String jobId;
  final String title;
  final String company;
  final String location;
  final String url;
  final String source;
  final String status;
  final DateTime? datePosted;
  final DateTime? dateCollected;
  final int? llmScore;
  final String? llmSummary;

  const Job({
    required this.jobId,
    required this.title,
    required this.company,
    required this.location,
    required this.url,
    required this.source,
    required this.status,
    this.datePosted,
    this.dateCollected,
    this.llmScore,
    this.llmSummary,
  });

  factory Job.fromJson(Map<String, dynamic> json) => Job(
        jobId:         json['job_id']    as String? ?? '',
        title:         json['title']     as String? ?? '',
        company:       json['company']   as String? ?? '',
        location:      json['location']  as String? ?? '',
        url:           json['url']       as String? ?? '',
        source:        json['source']    as String? ?? '',
        status:        json['status']    as String? ?? 'new',
        datePosted:    _parseDate(json['date_posted']),
        dateCollected: _parseDate(json['date_collected']),
        llmScore:      json['llm_score']   as int?,
        llmSummary:    json['llm_summary'] as String?,
      );

  Job copyWith({String? status}) => Job(
        jobId: jobId, title: title, company: company,
        location: location, url: url, source: source,
        status: status ?? this.status,
        datePosted: datePosted, dateCollected: dateCollected,
        llmScore: llmScore, llmSummary: llmSummary,
      );

  static DateTime? _parseDate(dynamic v) {
    if (v == null) return null;
    try { return DateTime.parse(v as String); } catch (_) { return null; }
  }
}

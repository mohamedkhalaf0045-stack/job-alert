import 'package:flutter/material.dart';
import '../models/job.dart';
import '../services/supabase_service.dart';
import '../services/github_service.dart';

/// Displayed before submitting a LinkedIn / Indeed Easy Apply application.
///
/// Flow:
///   1. Load CV profile from Supabase (cv_* bot_state keys).
///   2. Pre-fill every answer field from the profile.
///   3. User reviews / edits any field.
///   4. "Confirm & Apply" saves the answers to Supabase + triggers the
///      easy-apply.yml GitHub Actions workflow that does the actual form fill.
class ApplyPreviewScreen extends StatefulWidget {
  final Job job;
  const ApplyPreviewScreen({super.key, required this.job});

  @override
  State<ApplyPreviewScreen> createState() => _ApplyPreviewScreenState();
}

class _ApplyPreviewScreenState extends State<ApplyPreviewScreen> {
  final _formKey = GlobalKey<FormState>();

  // ── Controllers ─────────────────────────────────────────────────────────
  final _nameCtrl       = TextEditingController();
  final _emailCtrl      = TextEditingController();
  final _phoneCtrl      = TextEditingController();
  final _cityCtrl       = TextEditingController();
  final _titleCtrl      = TextEditingController();
  final _yearsCtrl      = TextEditingController();
  final _skillsCtrl     = TextEditingController();
  final _noticeCtrl     = TextEditingController();
  final _salaryCtrl     = TextEditingController();
  final _whyCtrl        = TextEditingController();

  // ── Switches ─────────────────────────────────────────────────────────────
  bool _authorized      = true;
  bool _sponsorship     = false;

  // ── State ────────────────────────────────────────────────────────────────
  bool _loading         = true;
  bool _submitting      = false;
  bool _submitted       = false;
  String? _errorMsg;

  @override
  void initState() {
    super.initState();
    _loadProfile();
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _phoneCtrl.dispose();
    _cityCtrl.dispose();
    _titleCtrl.dispose();
    _yearsCtrl.dispose();
    _skillsCtrl.dispose();
    _noticeCtrl.dispose();
    _salaryCtrl.dispose();
    _whyCtrl.dispose();
    super.dispose();
  }

  // ── Load CV profile from Supabase ────────────────────────────────────────

  Future<void> _loadProfile() async {
    setState(() { _loading = true; _errorMsg = null; });
    try {
      final cv = await SupabaseService.getCvProfile();

      final titles      = _splitCsv(cv['cv_job_titles'] ?? '');
      final skills      = _splitCsv(cv['cv_skills'] ?? '');
      final certs       = _splitCsv(cv['cv_certifications'] ?? '');
      final years       = int.tryParse(cv['cv_years_experience'] ?? '') ?? 0;
      final currentTitle = titles.isNotEmpty ? titles.first : 'IT Support Engineer';

      // Personal info — derive from email setting if available
      final settingEmail = cv['setting_email'] ?? '';
      final email = settingEmail.isNotEmpty
          ? settingEmail
          : 'mohamedkhalaf0045@gmail.com';

      _nameCtrl.text   = _nameFromEmail(email);
      _emailCtrl.text  = email;
      _phoneCtrl.text  = '';
      _cityCtrl.text   = _cityFromLocation(cv['setting_location'] ?? '');

      _titleCtrl.text  = currentTitle;
      _yearsCtrl.text  = years > 0 ? '$years' : '4';

      final topSkills  = skills.take(8).join(', ');
      _skillsCtrl.text = topSkills.isNotEmpty
          ? topSkills
          : 'IT Support, Windows Server, Active Directory, Networking';

      _noticeCtrl.text  = '1 month';
      _salaryCtrl.text  = '';

      _whyCtrl.text = _generateWhyText(
        jobTitle:     widget.job.title,
        company:      widget.job.company,
        currentTitle: currentTitle,
        years:        years > 0 ? years : 4,
        skills:       skills.take(5).toList(),
        certs:        certs,
        aiSummary:    widget.job.llmSummary ?? '',
      );

      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (mounted) setState(() { _loading = false; _errorMsg = e.toString(); });
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  static List<String> _splitCsv(String s) =>
      s.split(',').map((e) => e.trim()).where((e) => e.isNotEmpty).toList();

  static String _nameFromEmail(String email) {
    // "mohamedkhalaf0045@gmail.com" → "Mohamed Khalaf"
    final local = email.split('@').first;
    final cleaned = local.replaceAll(RegExp(r'\d+'), '');
    return cleaned
        .split(RegExp(r'[\._\-]'))
        .where((p) => p.isNotEmpty)
        .map((p) => p[0].toUpperCase() + p.substring(1).toLowerCase())
        .join(' ');
  }

  static String _cityFromLocation(String location) {
    if (location.isEmpty) return 'Abu Dhabi';
    // "United Arab Emirates" → blank (it's a country, not a city)
    if (location.toLowerCase().contains('emirat')) return 'Abu Dhabi';
    return location;
  }

  static String _generateWhyText({
    required String jobTitle,
    required String company,
    required String currentTitle,
    required int years,
    required List<String> skills,
    required List<String> certs,
    required String aiSummary,
  }) {
    final skillPhrase = skills.isNotEmpty ? skills.join(', ') : 'IT support and systems administration';
    final certPhrase  = certs.isNotEmpty  ? ' I hold ${certs.first}.' : '';
    final summaryLine = aiSummary.isNotEmpty ? '\n\n$aiSummary' : '';
    return 'I am excited to apply for the $jobTitle position at $company. '
        'With $years year${years == 1 ? "" : "s"} of hands-on experience as $currentTitle, '
        'I bring strong expertise in $skillPhrase.$certPhrase'
        '$summaryLine';
  }

  // ── Submit ────────────────────────────────────────────────────────────────

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Confirm Application'),
        content: RichText(
          text: TextSpan(
            style: Theme.of(context).textTheme.bodyMedium,
            children: [
              const TextSpan(text: 'Apply to '),
              TextSpan(
                text: widget.job.title,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              const TextSpan(text: ' at '),
              TextSpan(
                text: widget.job.company,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              const TextSpan(
                text: '\n\nThe Easy Apply form will be filled automatically '
                    'using the answers on this screen.',
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Apply'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() { _submitting = true; _errorMsg = null; });

    // Build the structured answers payload
    final answers = {
      'personal': {
        'full_name': _nameCtrl.text.trim(),
        'email':     _emailCtrl.text.trim(),
        'phone':     _phoneCtrl.text.trim(),
        'city':      _cityCtrl.text.trim(),
      },
      'experience': {
        'years':         int.tryParse(_yearsCtrl.text.trim()) ?? 4,
        'current_title': _titleCtrl.text.trim(),
        'skills':        _skillsCtrl.text.trim(),
      },
      'screening': {
        'authorized_to_work':   _authorized ? 'Yes' : 'No',
        'requires_sponsorship': _sponsorship ? 'Yes' : 'No',
        'notice_period':        _noticeCtrl.text.trim(),
        'expected_salary':      _salaryCtrl.text.trim(),
      },
      'open_text': {
        'why_interested': _whyCtrl.text.trim(),
      },
    };

    try {
      // 1. Store request in Supabase
      await SupabaseService.saveApplyRequest(
        jobId:    widget.job.jobId,
        jobUrl:   widget.job.url,
        jobTitle: widget.job.title,
        company:  widget.job.company,
        answers:  answers,
      );

      // 2. Trigger GitHub Actions easy-apply workflow
      final triggered = await GitHubService.triggerEasyApply(widget.job.jobId);

      // 3. Mark job as applied in jobs table
      await SupabaseService.updateJobStatus(widget.job.url, 'applied');

      if (mounted) {
        setState(() {
          _submitting = false;
          _submitted  = triggered;
          _errorMsg   = triggered ? null : 'Saved to queue. Could not trigger the worker — check GitHub PAT in Settings.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _errorMsg   = 'Error: $e';
        });
      }
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Easy Apply — Preview'),
        centerTitle: true,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _submitted
              ? _SuccessView(job: widget.job)
              : _buildForm(),
    );
  }

  Widget _buildForm() {
    final job = widget.job;
    return Form(
      key: _formKey,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // ── Job header ────────────────────────────────────────────────────
          _JobHeader(job: job),
          const SizedBox(height: 16),

          // ── Your details ─────────────────────────────────────────────────
          _Section('Your Details'),
          _Field(
            label: 'Full name *',
            controller: _nameCtrl,
            validator: (v) =>
                (v == null || v.trim().isEmpty) ? 'Required' : null,
          ),
          const SizedBox(height: 10),
          _Field(
            label: 'Email *',
            controller: _emailCtrl,
            keyboardType: TextInputType.emailAddress,
            validator: (v) =>
                (v == null || !v.contains('@')) ? 'Enter a valid email' : null,
          ),
          const SizedBox(height: 10),
          _Field(
            label: 'Phone number',
            controller: _phoneCtrl,
            hintText: '+971 XX XXX XXXX',
            keyboardType: TextInputType.phone,
          ),
          const SizedBox(height: 10),
          _Field(
            label: 'City',
            controller: _cityCtrl,
            hintText: 'Abu Dhabi',
          ),
          const SizedBox(height: 20),

          // ── Professional background ───────────────────────────────────────
          _Section('Professional Background'),
          _Field(
            label: 'Current / most recent title *',
            controller: _titleCtrl,
            validator: (v) =>
                (v == null || v.trim().isEmpty) ? 'Required' : null,
          ),
          const SizedBox(height: 10),
          _Field(
            label: 'Years of experience *',
            controller: _yearsCtrl,
            keyboardType: TextInputType.number,
            validator: (v) {
              if (v == null || v.trim().isEmpty) return 'Required';
              if (int.tryParse(v.trim()) == null) return 'Must be a number';
              return null;
            },
          ),
          const SizedBox(height: 10),
          _Field(
            label: 'Skills summary (shown on application)',
            controller: _skillsCtrl,
            maxLines: 3,
            hintText: 'Windows Server, Active Directory, Networking...',
          ),
          const SizedBox(height: 20),

          // ── Screening ─────────────────────────────────────────────────────
          _Section('Screening Questions'),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Authorized to work in UAE?'),
            subtitle: const Text('Will answer "Yes" on the form'),
            value: _authorized,
            onChanged: (v) => setState(() => _authorized = v),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Requires visa sponsorship?'),
            subtitle: const Text('Will answer "Yes" on the form if enabled'),
            value: _sponsorship,
            onChanged: (v) => setState(() => _sponsorship = v),
          ),
          const SizedBox(height: 10),
          _Field(
            label: 'Notice period',
            controller: _noticeCtrl,
            hintText: 'Immediately / 2 weeks / 1 month',
          ),
          const SizedBox(height: 10),
          _Field(
            label: 'Expected salary (leave blank to skip)',
            controller: _salaryCtrl,
            hintText: 'e.g. 8000 AED',
            keyboardType: TextInputType.text,
          ),
          const SizedBox(height: 20),

          // ── Why this role ─────────────────────────────────────────────────
          _Section('Why This Role'),
          _Field(
            label: 'Statement of interest (editable)',
            controller: _whyCtrl,
            maxLines: 6,
            hintText: 'Why are you applying for this position?',
          ),
          const SizedBox(height: 24),

          // ── Error ──────────────────────────────────────────────────────────
          if (_errorMsg != null) ...[
            Card(
              color: Colors.red.shade50,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Icon(Icons.error_outline, color: Colors.red.shade700),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(_errorMsg!,
                          style: TextStyle(color: Colors.red.shade700)),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
          ],

          // ── Notice ─────────────────────────────────────────────────────────
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.amber.shade50,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.amber.shade300),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline, color: Colors.amber.shade800, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Answers above will be used to auto-fill the Easy Apply form '
                    'via a background cloud worker. Review every field before confirming.',
                    style: TextStyle(fontSize: 12, color: Colors.amber.shade900),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),

          // ── Confirm button ────────────────────────────────────────────────
          _submitting
              ? const Center(child: CircularProgressIndicator())
              : FilledButton.icon(
                  onPressed: _submit,
                  icon: const Icon(Icons.send),
                  label: const Text('Confirm & Apply'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    backgroundColor: Colors.teal,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8)),
                  ),
                ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _loadProfile,
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('Reload from CV'),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }
}

// ── Success view ──────────────────────────────────────────────────────────────

class _SuccessView extends StatelessWidget {
  final Job job;
  const _SuccessView({required this.job});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.check_circle, color: Colors.teal, size: 72),
            const SizedBox(height: 20),
            Text(
              'Application Submitted!',
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            Text(
              '${job.title} at ${job.company}',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(color: Colors.grey.shade700),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.teal.shade50,
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text(
                'The Easy Apply form is being filled by the cloud worker. '
                'Check the Cloud tab to see the job-alert workflow run status.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 13),
              ),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.arrow_back),
              label: const Text('Back to Job'),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Shared widgets ────────────────────────────────────────────────────────────

class _JobHeader extends StatelessWidget {
  final Job job;
  const _JobHeader({required this.job});

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(job.title,
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Text('${job.company}  •  ${job.location}',
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 8),
            Row(children: [
              _Chip(
                label: job.source,
                color: job.source.toLowerCase().contains('linkedin')
                    ? Colors.blue
                    : Colors.orange,
              ),
              const SizedBox(width: 8),
              _Chip(label: 'Easy Apply', color: Colors.teal),
            ]),
          ],
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final Color color;
  const _Chip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(label,
          style: const TextStyle(
              color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  const _Section(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10, top: 4),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.07),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(
          title,
          style: Theme.of(context).textTheme.titleSmall?.copyWith(
                color: Theme.of(context).colorScheme.primary,
                fontWeight: FontWeight.w700,
              ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  final String label;
  final TextEditingController controller;
  final String? hintText;
  final int maxLines;
  final TextInputType? keyboardType;
  final String? Function(String?)? validator;

  const _Field({
    required this.label,
    required this.controller,
    this.hintText,
    this.maxLines = 1,
    this.keyboardType,
    this.validator,
  });

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller:   controller,
      maxLines:     maxLines,
      keyboardType: keyboardType,
      validator:    validator,
      decoration: InputDecoration(
        labelText: label,
        hintText:  hintText,
        border:    const OutlineInputBorder(),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      ),
    );
  }
}

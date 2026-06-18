import 'package:flutter/material.dart';
import '../main.dart';
import '../services/supabase_service.dart';

// Preset location chips shown on Step 3
const _kLocations = [
  'United Arab Emirates', 'Dubai', 'Abu Dhabi', 'Sharjah', 'Ajman',
  'Egypt', 'Saudi Arabia', 'Qatar', 'Kuwait',
];

class OnboardingScreen extends StatefulWidget {
  final VoidCallback onComplete;
  const OnboardingScreen({super.key, required this.onComplete});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  int _step = 1; // 1=source  2=keywords  3=locations

  // Step 1
  String _source = '';   // 'cv' | 'linkedin' | ''
  String _linkedInMode = 'url'; // 'url' | 'text'
  final _textCtrl    = TextEditingController();
  final _urlCtrl     = TextEditingController();
  bool   _extracting   = false;
  String _extractError = '';

  // Step 2
  final _kwCtrl    = TextEditingController();
  List<String> _keywords  = [];
  List<String> _suggested = [];

  // Step 3
  final _locCtrl = TextEditingController();
  List<String> _selectedLocs  = [];
  List<String> _suggestedLocs = [];

  String _excludes  = '';
  bool   _saving    = false;
  String _saveError = '';

  @override
  void dispose() {
    _textCtrl.dispose();
    _urlCtrl.dispose();
    _kwCtrl.dispose();
    _locCtrl.dispose();
    super.dispose();
  }

  // ── Keyword helpers ───────────────────────────────────────────────────────

  void _addKeyword(String kw) {
    final t = kw.trim();
    if (t.isNotEmpty && !_keywords.contains(t)) {
      setState(() => _keywords = [..._keywords, t]);
    }
  }

  void _removeKeyword(String kw) =>
      setState(() => _keywords = _keywords.where((k) => k != kw).toList());

  // ── Location helpers ──────────────────────────────────────────────────────

  void _toggleLoc(String loc) => setState(() {
    if (_selectedLocs.contains(loc)) {
      _selectedLocs = _selectedLocs.where((l) => l != loc).toList();
    } else {
      _selectedLocs = [..._selectedLocs, loc];
    }
  });

  // ── Step 1: Extract from LinkedIn URL or pasted text ─────────────────────

  Future<void> _extractProfile() async {
    setState(() { _extracting = true; _extractError = ''; });
    try {
      if (_source == 'linkedin' && _linkedInMode == 'url') {
        final url = _urlCtrl.text.trim();
        if (!url.contains('linkedin.com')) {
          setState(() { _extractError = 'Enter a valid LinkedIn profile URL.'; _extracting = false; });
          return;
        }
        // Fetch the public LinkedIn page
        final response = await SupabaseService.fetchLinkedInUrl(url);
        if (response == null) {
          setState(() { _extractError = 'Could not fetch LinkedIn profile. Try the "Paste text" option instead.'; _extracting = false; });
          return;
        }
        setState(() {
          _suggested    = response.jobTitles;
          _suggestedLocs = response.locations;
          _extracting   = false;
        });
      } else {
        // Text paste — client-side extraction
        final text = _textCtrl.text.trim();
        if (text.length < 20) {
          setState(() { _extractError = 'Paste at least a few lines of text.'; _extracting = false; });
          return;
        }
        final candidates = text
            .split(RegExp(r'[\n,·|•]'))
            .map((s) => s.trim())
            .where((s) => s.length > 3 && s.length < 50)
            .where((s) => RegExp(r'^[A-Z]').hasMatch(s))
            .take(8)
            .toList();
        final autoLocs = _kLocations
            .where((loc) => text.toLowerCase().contains(loc.toLowerCase()))
            .toList();
        setState(() {
          _suggested     = candidates;
          _suggestedLocs = autoLocs;
          _extracting    = false;
        });
      }
    } catch (e) {
      setState(() { _extractError = 'Something went wrong. Try the "Paste text" option instead.'; _extracting = false; });
    }
  }

  // ── Save ──────────────────────────────────────────────────────────────────

  Future<void> _save() async {
    if (_keywords.isEmpty || _selectedLocs.isEmpty) return;
    setState(() { _saving = true; _saveError = ''; });

    final ok = await SupabaseService.saveUserPreferences(
      keywords:        _keywords,
      locations:       _selectedLocs,
      excludeKeywords: _excludes
          .split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).toList(),
      alertFrequency: 'instant',
    );

    if (!mounted) return;
    if (!ok) {
      setState(() { _saving = false; _saveError = 'Save failed — check connection.'; });
      return;
    }
    widget.onComplete(); // tells _PrefsGate to re-check → shows _Shell
  }

  // ── Scaffold ──────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Set up job search'),
        automaticallyImplyLeading: _step > 1,
        leading: _step > 1
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () => setState(() => _step--),
              )
            : null,
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(4),
          child: _StepBar(current: _step, total: 3),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: switch (_step) {
            1 => _buildSource(),
            2 => _buildKeywords(),
            3 => _buildLocations(),
            _ => const SizedBox.shrink(),
          },
        ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Step 1: Profile source
  // ─────────────────────────────────────────────────────────────────────────

  Widget _buildSource() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text('Import your profile', style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 6),
      const Text(
        'Paste your CV or LinkedIn profile so we can suggest job titles. '
        'Or skip and enter keywords manually.',
        style: TextStyle(color: kMuted, fontSize: 14, height: 1.5),
      ),
      const SizedBox(height: 20),

      Row(children: [
        Expanded(child: _SourceCard(
          emoji: '📄', label: 'CV', selected: _source == 'cv',
          onTap: () => setState(() { _source = 'cv'; _textCtrl.clear(); _extractError = ''; }),
        )),
        const SizedBox(width: 12),
        Expanded(child: _SourceCard(
          emoji: '💼', label: 'LinkedIn', selected: _source == 'linkedin',
          onTap: () => setState(() { _source = 'linkedin'; _textCtrl.clear(); _urlCtrl.clear(); _extractError = ''; }),
        )),
      ]),

      if (_source.isNotEmpty) ...[
        const SizedBox(height: 16),

        // LinkedIn: URL / Text toggle
        if (_source == 'linkedin') ...[
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: kBorder),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(children: [
              Expanded(child: GestureDetector(
                onTap: () => setState(() { _linkedInMode = 'url'; _extractError = ''; }),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(
                    color: _linkedInMode == 'url' ? kAccent : Colors.transparent,
                    borderRadius: const BorderRadius.horizontal(left: Radius.circular(7)),
                  ),
                  alignment: Alignment.center,
                  child: Text('Profile URL',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600,
                      color: _linkedInMode == 'url' ? Colors.white : kMuted)),
                ),
              )),
              Expanded(child: GestureDetector(
                onTap: () => setState(() { _linkedInMode = 'text'; _extractError = ''; }),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(
                    color: _linkedInMode == 'text' ? kAccent : Colors.transparent,
                    borderRadius: const BorderRadius.horizontal(right: Radius.circular(7)),
                  ),
                  alignment: Alignment.center,
                  child: Text('Paste text',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600,
                      color: _linkedInMode == 'text' ? Colors.white : kMuted)),
                ),
              )),
            ]),
          ),
          const SizedBox(height: 12),
        ],

        if (_source == 'linkedin' && _linkedInMode == 'url') ...[
          const Text('Your LinkedIn profile URL:',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500)),
          const SizedBox(height: 8),
          TextField(
            controller: _urlCtrl,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(
              hintText: 'https://www.linkedin.com/in/yourname',
            ),
          ),
        ] else ...[
          Text(
            _source == 'cv'
                ? 'Paste your CV text:'
                : 'Copy your LinkedIn headline + experience and paste:',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _textCtrl,
            maxLines: 6,
            decoration: InputDecoration(
              hintText: _source == 'cv'
                  ? 'IT Support Engineer\n5 years experience\nWindows Server, Azure AD…'
                  : 'IT Support Engineer at Acme · Dubai\nSkills: Windows Server…',
            ),
          ),
        ],

        if (_extractError.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(_extractError, style: const TextStyle(color: kDanger, fontSize: 13)),
          ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _extracting ? null : _extractProfile,
          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44)),
          child: _extracting
              ? const SizedBox(height: 18, width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text('Extract keywords →'),
        ),
      ],

      if (_suggested.isNotEmpty) ...[
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: const Color(0xFFEFFEF6),
            borderRadius: BorderRadius.circular(8),
          ),
          child: const Row(children: [
            Icon(Icons.check_circle, color: kSuccess, size: 16),
            SizedBox(width: 6),
            Expanded(child: Text('Keywords extracted — tap Continue to review',
                style: TextStyle(color: kSuccess, fontSize: 13))),
          ]),
        ),
      ],

      const SizedBox(height: 24),
      FilledButton(
        onPressed: _suggested.isNotEmpty
            ? () {
                for (final s in _suggested) { _addKeyword(s); }
                setState(() => _step = 2);
              }
            : null,
        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44)),
        child: const Text('Continue →'),
      ),
      const SizedBox(height: 10),
      OutlinedButton(
        onPressed: () => setState(() => _step = 2),
        style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(44)),
        child: const Text('Skip — enter keywords manually'),
      ),
    ],
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Step 2: Keywords (mandatory)
  // ─────────────────────────────────────────────────────────────────────────

  Widget _buildKeywords() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text('What jobs are you looking for?',
          style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 6),
      const Text('Required — at least one keyword to continue.',
          style: TextStyle(color: kDanger, fontSize: 13)),
      const SizedBox(height: 16),

      if (_suggested.isNotEmpty) ...[
        const Text('Suggestions:', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: kMuted)),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8, runSpacing: 8,
          children: _suggested.map((kw) {
            final added = _keywords.contains(kw);
            return FilterChip(
              label: Text(kw, style: const TextStyle(fontSize: 12)),
              selected: added,
              onSelected: (_) => added ? _removeKeyword(kw) : _addKeyword(kw),
              selectedColor: const Color(0x1A5E6AD2),
              checkmarkColor: kAccent,
            );
          }).toList(),
        ),
        const SizedBox(height: 16),
      ],

      TextField(
        controller: _kwCtrl,
        decoration: const InputDecoration(
          labelText: 'Add keyword',
          hintText: 'e.g. IT Support, Sysadmin',
          helperText: 'Press Enter after each keyword',
        ),
        onSubmitted: (v) { _addKeyword(v); _kwCtrl.clear(); },
      ),

      if (_keywords.isNotEmpty) ...[
        const SizedBox(height: 12),
        Wrap(
          spacing: 8, runSpacing: 8,
          children: _keywords.map((kw) => Chip(
            label: Text(kw, style: const TextStyle(fontSize: 12)),
            deleteIcon: const Icon(Icons.close, size: 14),
            onDeleted: () => _removeKeyword(kw),
            backgroundColor: const Color(0xFFEEF2FF),
            labelStyle: const TextStyle(color: kAccent),
            side: const BorderSide(color: Color(0xFFBFC4F5)),
          )).toList(),
        ),
      ] else
        const Padding(
          padding: EdgeInsets.only(top: 8),
          child: Text('At least one keyword required',
              style: TextStyle(color: kDanger, fontSize: 12)),
        ),

      const SizedBox(height: 24),
      FilledButton(
        onPressed: _keywords.isEmpty
            ? null
            : () {
                if (_suggestedLocs.isNotEmpty && _selectedLocs.isEmpty) {
                  for (final l in _suggestedLocs) { _toggleLoc(l); }
                }
                setState(() => _step = 3);
              },
        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44)),
        child: const Text('Continue →'),
      ),
    ],
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Step 3: Locations (mandatory)
  // ─────────────────────────────────────────────────────────────────────────

  Widget _buildLocations() {
    final customLocs = _selectedLocs.where((l) => !_kLocations.contains(l)).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Where are you looking?', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 6),
        const Text('Required — select at least one location.',
            style: TextStyle(color: kDanger, fontSize: 13)),

        if (_suggestedLocs.isNotEmpty) ...[
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            decoration: BoxDecoration(
              color: const Color(0xFFEFFEF6), borderRadius: BorderRadius.circular(8)),
            child: const Text('Pre-selected from your profile — adjust as needed',
                style: TextStyle(color: kSuccess, fontSize: 12)),
          ),
        ],

        const SizedBox(height: 16),
        Wrap(
          spacing: 8, runSpacing: 8,
          children: _kLocations.map((loc) {
            final sel  = _selectedLocs.contains(loc);
            final hint = _suggestedLocs.contains(loc);
            return FilterChip(
              label: Text(loc, style: const TextStyle(fontSize: 12)),
              selected: sel,
              onSelected: (_) => _toggleLoc(loc),
              selectedColor: const Color(0x1A5E6AD2),
              checkmarkColor: kAccent,
              side: BorderSide(color: sel ? kAccent : hint ? kSuccess : kBorder),
              labelStyle: TextStyle(color: sel ? kAccent : hint ? kSuccess : kFg2),
            );
          }).toList(),
        ),

        const SizedBox(height: 12),
        TextField(
          controller: _locCtrl,
          decoration: const InputDecoration(
            labelText: 'Other location',
            hintText: 'e.g. Bahrain (press Enter)',
          ),
          onSubmitted: (v) {
            final t = v.trim();
            if (t.isNotEmpty && !_selectedLocs.contains(t)) {
              setState(() => _selectedLocs = [..._selectedLocs, t]);
            }
            _locCtrl.clear();
          },
        ),

        if (customLocs.isNotEmpty) ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 8, runSpacing: 8,
            children: customLocs.map((loc) => Chip(
              label: Text(loc, style: const TextStyle(fontSize: 12)),
              deleteIcon: const Icon(Icons.close, size: 14),
              onDeleted: () => _toggleLoc(loc),
            )).toList(),
          ),
        ],

        if (_selectedLocs.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('Select at least one location',
                style: TextStyle(color: kDanger, fontSize: 12)),
          ),

        const SizedBox(height: 16),
        TextField(
          decoration: const InputDecoration(
            labelText: 'Exclude keywords (optional)',
            hintText: 'Senior, Manager, Intern',
            helperText: 'Jobs with these words will be hidden',
          ),
          onChanged: (v) => _excludes = v,
        ),

        if (_saveError.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text(_saveError, style: const TextStyle(color: kDanger, fontSize: 13)),
          ),

        const SizedBox(height: 24),
        _saving
            ? const Center(child: CircularProgressIndicator())
            : FilledButton(
                onPressed: (_keywords.isEmpty || _selectedLocs.isEmpty) ? null : _save,
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44)),
                child: const Text('Start finding jobs →'),
              ),
      ],
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Step progress bar
// ─────────────────────────────────────────────────────────────────────────────

class _StepBar extends StatelessWidget {
  final int current;
  final int total;
  const _StepBar({required this.current, required this.total});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: List.generate(total, (i) => Expanded(
        child: Container(
          height: 3,
          margin: EdgeInsets.only(left: i == 0 ? 0 : 2),
          color: i < current ? kAccent : kBorder,
        ),
      )),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Source option card
// ─────────────────────────────────────────────────────────────────────────────

class _SourceCard extends StatelessWidget {
  final String emoji;
  final String label;
  final bool   selected;
  final VoidCallback onTap;
  const _SourceCard({required this.emoji, required this.label,
      required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(vertical: 16),
        decoration: BoxDecoration(
          color: selected ? const Color(0xFFEEF2FF) : kSurface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? kAccent : kBorder,
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(emoji, style: const TextStyle(fontSize: 24)),
          const SizedBox(height: 6),
          Text(label, style: TextStyle(
            fontWeight: FontWeight.w600, fontSize: 13,
            color: selected ? kAccent : kFg,
          )),
        ]),
      ),
    );
  }
}

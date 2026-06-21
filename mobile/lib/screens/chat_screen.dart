import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';
import '../config.dart';
import '../main.dart' show kAccent, kBorder, kBorderSoft, kFg, kFg2, kMuted, kSurface;

const _kSuggestedQuestions = [
  'Am I a good fit for this job?',
  'What interview questions should I prepare?',
  'What salary should I negotiate?',
  'How can I improve my application?',
];

class ChatMessage {
  final String role;    // 'user' | 'assistant'
  final String content;
  const ChatMessage({required this.role, required this.content});
  Map<String, dynamic> toJson() => {'role': role, 'content': content};
}

/// Optional job context — passed in when the user taps "Ask AI" on a job card.
class ChatJobContext {
  final String? title;
  final String? company;
  final String? location;
  final String? llmSummary;
  final int?    matchScore;
  final List<String> matchedSkills;
  final List<String> missingSkills;

  const ChatJobContext({
    this.title,
    this.company,
    this.location,
    this.llmSummary,
    this.matchScore,
    this.matchedSkills = const [],
    this.missingSkills = const [],
  });

  Map<String, dynamic> toJson() => {
    if (title       != null) 'title':          title,
    if (company     != null) 'company':        company,
    if (location    != null) 'location':       location,
    if (llmSummary  != null) 'llm_summary':    llmSummary,
    if (matchScore  != null) 'match_score':    matchScore,
    if (matchedSkills.isNotEmpty) 'matched_skills': matchedSkills,
    if (missingSkills.isNotEmpty) 'missing_skills': missingSkills,
  };
}

class ChatScreen extends StatefulWidget {
  final ChatJobContext? jobContext;
  const ChatScreen({super.key, this.jobContext});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _msgCtrl    = TextEditingController();
  final _scrollCtrl = ScrollController();
  final List<ChatMessage> _messages = [];
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _addGreeting();
  }

  @override
  void dispose() {
    _msgCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _addGreeting() {
    final job = widget.jobContext;
    final text = job?.title != null
        ? 'Hi! I can help you with your application for **${job!.title}**'
          '${job.company != null ? ' at ${job.company}' : ''}. '
          'Ask me about interview prep, salary, or whether you\'re a good fit.'
        : 'Hi! I\'m your career assistant. Ask me about interview preparation, '
          'salary negotiation, CV advice, or whether to apply for a job.';
    _messages.add(ChatMessage(role: 'assistant', content: text));
  }

  Future<void> _send(String text) async {
    final t = text.trim();
    if (t.isEmpty || _loading) return;
    _msgCtrl.clear();

    setState(() {
      _messages.add(ChatMessage(role: 'user', content: t));
      _loading = true;
    });
    _scrollToBottom();

    final token = Supabase.instance.client.auth.currentSession?.accessToken ?? '';
    final baseUrl = Config.webAppUrl.isNotEmpty ? Config.webAppUrl : '';

    if (baseUrl.isEmpty) {
      setState(() {
        _messages.add(const ChatMessage(
          role: 'assistant',
          content: 'Chat not configured yet. Add WEB_APP_URL when building the APK.',
        ));
        _loading = false;
      });
      return;
    }

    try {
      final res = await http.post(
        Uri.parse('$baseUrl/api/mobile/chat'),
        headers: {
          'Content-Type':  'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'messages': _messages
              .where((m) => m.role == 'user' || m.role == 'assistant')
              .map((m) => m.toJson())
              .toList(),
          if (widget.jobContext != null) 'job': widget.jobContext!.toJson(),
        }),
      ).timeout(const Duration(seconds: 30));

      final data = jsonDecode(res.body) as Map<String, dynamic>;
      final reply = res.statusCode == 200
          ? (data['reply'] as String? ?? 'No response.')
          : (data['error'] as String? ?? 'Something went wrong (${res.statusCode}).');

      if (mounted) setState(() => _messages.add(ChatMessage(role: 'assistant', content: reply)));
    } catch (e) {
      if (mounted) setState(() => _messages.add(ChatMessage(
        role: 'assistant',
        content: 'Connection error. Please try again.',
      )));
    } finally {
      if (mounted) setState(() => _loading = false);
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _clearChat() {
    setState(() {
      _messages.clear();
      _addGreeting();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Job context banner
        if (widget.jobContext?.title != null)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: kAccent.withValues(alpha: 0.08),
            child: Text(
              'Discussing: ${widget.jobContext!.title}'
              '${widget.jobContext!.company != null ? ' @ ${widget.jobContext!.company}' : ''}'
              '${widget.jobContext!.matchScore != null ? ' · ${widget.jobContext!.matchScore}/10' : ''}',
              style: const TextStyle(
                fontSize: 12,
                color: kAccent,
                fontWeight: FontWeight.w500,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),

        // Messages
        Expanded(
          child: ListView.builder(
            controller: _scrollCtrl,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            itemCount: _messages.length + (_loading ? 1 : 0) + (_showSuggestions ? 1 : 0),
            itemBuilder: (ctx, i) {
              // Suggested questions block after greeting
              if (_showSuggestions && i == 1) {
                return _SuggestedQuestions(onTap: _send);
              }

              // Offset index for suggestions block
              final msgIndex = _showSuggestions && i > 1 ? i - 1 : i;

              // Loading indicator at end
              if (_loading && msgIndex == _messages.length) {
                return const _TypingIndicator();
              }

              if (msgIndex >= _messages.length) return const SizedBox.shrink();
              return _Bubble(msg: _messages[msgIndex]);
            },
          ),
        ),

        // Input bar
        Container(
          decoration: const BoxDecoration(
            color: kSurface,
            border: Border(top: BorderSide(color: kBorder)),
          ),
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
          child: SafeArea(
            top: false,
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _msgCtrl,
                    decoration: InputDecoration(
                      hintText: 'Ask anything...',
                      hintStyle: const TextStyle(color: kMuted, fontSize: 14),
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 10),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(24),
                        borderSide: const BorderSide(color: kBorder),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(24),
                        borderSide: const BorderSide(color: kBorder),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(24),
                        borderSide: const BorderSide(color: kAccent, width: 1.5),
                      ),
                      filled: true,
                      fillColor: kSurface,
                    ),
                    style: const TextStyle(fontSize: 14),
                    textInputAction: TextInputAction.send,
                    onSubmitted: _send,
                    enabled: !_loading,
                    maxLines: 3,
                    minLines: 1,
                  ),
                ),
                const SizedBox(width: 8),
                GestureDetector(
                  onTap: _loading ? null : () => _send(_msgCtrl.text),
                  child: Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                      color: _loading ? kMuted : kAccent,
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.send, color: Colors.white, size: 18),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  bool get _showSuggestions =>
      _messages.length == 1 && _messages.first.role == 'assistant' && !_loading;
}

// ── Bubble ───────────────────────────────────────────────────────────────────

class _Bubble extends StatelessWidget {
  final ChatMessage msg;
  const _Bubble({required this.msg});

  @override
  Widget build(BuildContext context) {
    final isUser = msg.role == 'user';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        mainAxisAlignment:
            isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!isUser) ...[
            CircleAvatar(
              radius: 14,
              backgroundColor: kAccent,
              child: const Text('AI',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 9,
                      fontWeight: FontWeight.w700)),
            ),
            const SizedBox(width: 6),
          ],
          Flexible(
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: isUser ? kAccent : kBorderSoft,
                borderRadius: BorderRadius.only(
                  topLeft:     const Radius.circular(18),
                  topRight:    const Radius.circular(18),
                  bottomLeft:  Radius.circular(isUser ? 18 : 4),
                  bottomRight: Radius.circular(isUser ? 4 : 18),
                ),
              ),
              child: _RichText(
                text: msg.content,
                color: isUser ? Colors.white : kFg,
              ),
            ),
          ),
          if (isUser) const SizedBox(width: 6),
        ],
      ),
    );
  }
}

// ── RichText — bold **text** support ─────────────────────────────────────────

class _RichText extends StatelessWidget {
  final String text;
  final Color color;
  const _RichText({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    final spans = <TextSpan>[];
    final parts  = text.split(RegExp(r'\*\*'));
    for (int i = 0; i < parts.length; i++) {
      spans.add(TextSpan(
        text: parts[i],
        style: TextStyle(
          fontSize: 14,
          color: color,
          height: 1.45,
          fontWeight: i.isOdd ? FontWeight.w600 : FontWeight.normal,
        ),
      ));
    }
    return RichText(text: TextSpan(children: spans));
  }
}

// ── Typing indicator ──────────────────────────────────────────────────────────

class _TypingIndicator extends StatefulWidget {
  const _TypingIndicator();

  @override
  State<_TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<_TypingIndicator>
    with TickerProviderStateMixin {
  late final List<AnimationController> _ctrls;
  late final List<Animation<double>>   _anims;

  @override
  void initState() {
    super.initState();
    _ctrls = List.generate(3, (i) => AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat(reverse: true, period: const Duration(milliseconds: 1200)));
    _anims = List.generate(3, (i) {
      _ctrls[i].forward();
      return Tween<double>(begin: 0, end: -5).animate(
        CurvedAnimation(
          parent: _ctrls[i],
          curve: Interval(i * 0.15, 0.6 + i * 0.15, curve: Curves.easeInOut),
        ),
      );
    });
    for (int i = 0; i < 3; i++) {
      Future.delayed(Duration(milliseconds: i * 150), () {
        if (mounted) _ctrls[i].repeat(reverse: true);
      });
    }
  }

  @override
  void dispose() {
    for (final c in _ctrls) c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        children: [
          CircleAvatar(
            radius: 14,
            backgroundColor: kAccent,
            child: const Text('AI',
                style: TextStyle(
                    color: Colors.white,
                    fontSize: 9,
                    fontWeight: FontWeight.w700)),
          ),
          const SizedBox(width: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              color: kBorderSoft,
              borderRadius: const BorderRadius.only(
                topLeft:     Radius.circular(18),
                topRight:    Radius.circular(18),
                bottomRight: Radius.circular(18),
                bottomLeft:  Radius.circular(4),
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: List.generate(3, (i) => AnimatedBuilder(
                animation: _anims[i],
                builder: (_, __) => Transform.translate(
                  offset: Offset(0, _anims[i].value),
                  child: Container(
                    width: 7,
                    height: 7,
                    margin: const EdgeInsets.symmetric(horizontal: 2),
                    decoration: BoxDecoration(
                      color: kMuted,
                      shape: BoxShape.circle,
                    ),
                  ),
                ),
              )),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Suggested questions ───────────────────────────────────────────────────────

class _SuggestedQuestions extends StatelessWidget {
  final void Function(String) onTap;
  const _SuggestedQuestions({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: _kSuggestedQuestions.map((q) => Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: GestureDetector(
            onTap: () => onTap(q),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: kAccent.withValues(alpha: 0.07),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: kAccent.withValues(alpha: 0.25)),
              ),
              child: Text(
                q,
                style: const TextStyle(
                    fontSize: 13, color: kAccent, fontWeight: FontWeight.w500),
              ),
            ),
          ),
        )).toList(),
      ),
    );
  }
}

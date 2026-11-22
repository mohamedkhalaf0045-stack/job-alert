import 'package:flutter/material.dart';
import '../services/apply_answers_store.dart';

/// Answers the cloud worker reuses on every Easy Apply form.
///
/// Top: common questions (phone, visa, salary, languages ...).
/// Bottom: answers to specific questions, added here or saved from an
/// application that stopped because a question had no answer.
class SavedAnswersScreen extends StatefulWidget {
  const SavedAnswersScreen({super.key});

  @override
  State<SavedAnswersScreen> createState() => _SavedAnswersScreenState();
}

class _SavedAnswersScreenState extends State<SavedAnswersScreen> {
  final Map<String, TextEditingController> _ctrls = {
    for (final k in ApplyAnswersStore.commonFields.keys) k: TextEditingController(),
  };
  List<SavedQA> _custom = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in _ctrls.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    final bank = await ApplyAnswersStore.loadBank();
    final custom = await ApplyAnswersStore.loadCustom();
    if (!mounted) return;
    setState(() {
      bank.forEach((k, v) => _ctrls[k]?.text = v);
      _custom = custom;
      _loading = false;
    });
  }

  Future<void> _save() async {
    await ApplyAnswersStore.saveBank(
        _ctrls.map((k, c) => MapEntry(k, c.text.trim())));
    await ApplyAnswersStore.saveCustom(_custom);
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('Answers saved')));
    Navigator.pop(context, true);
  }

  Future<void> _editCustom([int? index]) async {
    final q = TextEditingController(text: index == null ? '' : _custom[index].question);
    final a = TextEditingController(text: index == null ? '' : _custom[index].answer);
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(index == null ? 'Add answer' : 'Edit answer'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: q,
              maxLines: 2,
              decoration: const InputDecoration(
                  labelText: 'Question (as it appears on the form)'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: a,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Your answer'),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('OK')),
        ],
      ),
    );
    if (ok == true && q.text.trim().isNotEmpty && a.text.trim().isNotEmpty) {
      setState(() {
        final item = SavedQA(q.text.trim(), a.text.trim());
        if (index == null) {
          _custom.add(item);
        } else {
          _custom[index] = item;
        }
      });
    }
    q.dispose();
    a.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Saved Answers'),
        actions: [
          TextButton(onPressed: _loading ? null : _save, child: const Text('Save')),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(
                  'Easy Apply uses these answers on every application. '
                  'Leave a field empty if you never want it filled automatically. '
                  'They are stored on this phone and sent with each application.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 16),
                for (final e in ApplyAnswersStore.commonFields.entries) ...[
                  TextField(
                    controller: _ctrls[e.key],
                    decoration: InputDecoration(
                      labelText: e.value,
                      border: const OutlineInputBorder(),
                      contentPadding:
                          const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    ),
                  ),
                  const SizedBox(height: 10),
                ],
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: Text('Answers to specific questions',
                          style: Theme.of(context)
                              .textTheme
                              .titleSmall
                              ?.copyWith(fontWeight: FontWeight.bold)),
                    ),
                    TextButton.icon(
                      onPressed: () => _editCustom(),
                      icon: const Icon(Icons.add),
                      label: const Text('Add'),
                    ),
                  ],
                ),
                if (_custom.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      'None yet. When an application stops on a question it '
                      'cannot answer, your answer is saved here for next time.',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                for (var i = 0; i < _custom.length; i++)
                  Card(
                    child: ListTile(
                      title: Text(_custom[i].question),
                      subtitle: Text(_custom[i].answer),
                      onTap: () => _editCustom(i),
                      trailing: IconButton(
                        icon: const Icon(Icons.delete_outline),
                        onPressed: () => setState(() => _custom.removeAt(i)),
                      ),
                    ),
                  ),
                const SizedBox(height: 24),
                FilledButton(onPressed: _save, child: const Text('Save answers')),
                const SizedBox(height: 32),
              ],
            ),
    );
  }
}

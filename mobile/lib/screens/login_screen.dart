import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../main.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _passCtrl  = TextEditingController();
  bool   _loading  = false;
  bool   _isSignUp = false;
  String? _error;

  // Set after successful sign-up — shows "check your email" state.
  bool   _waitingConfirmation = false;
  String _confirmedEmail      = '';

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email    = _emailCtrl.text.trim();
    final password = _passCtrl.text;
    if (email.isEmpty || password.isEmpty) return;
    setState(() { _loading = true; _error = null; });
    try {
      if (_isSignUp) {
        await Supabase.instance.client.auth
            .signUp(email: email, password: password);
        // signUp succeeded — Supabase sent a confirmation email.
        // Session is NOT active yet; show the "check email" screen.
        if (mounted) {
          setState(() {
            _loading              = false;
            _waitingConfirmation  = true;
            _confirmedEmail       = email;
          });
        }
      } else {
        await Supabase.instance.client.auth
            .signInWithPassword(email: email, password: password);
        // On success _AuthGate will react to onAuthStateChange automatically.
      }
    } on AuthException catch (e) {
      String msg = e.message;
      // Friendly message for the most common confirmation error.
      if (msg.toLowerCase().contains('email not confirmed')) {
        msg = 'Email not confirmed yet — check your inbox for the verification link.';
        if (mounted) {
          setState(() {
            _loading             = false;
            _waitingConfirmation = true;
            _confirmedEmail      = email;
            _error               = null;
          });
          return;
        }
      }
      if (mounted) setState(() { _error = msg; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Future<void> _resend() async {
    setState(() { _loading = true; _error = null; });
    try {
      await Supabase.instance.client.auth.resend(
        type: OtpType.signup,
        email: _confirmedEmail,
      );
      if (mounted) {
        setState(() => _loading = false);
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Confirmation email resent — check your inbox.'),
          backgroundColor: Colors.green,
        ));
      }
    } on AuthException catch (e) {
      if (mounted) setState(() { _error = e.message; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  void _backToSignIn() => setState(() {
    _waitingConfirmation = false;
    _isSignUp            = false;
    _error               = null;
    _passCtrl.clear();
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 360),
              child: _waitingConfirmation
                  ? _buildConfirmationWaiting()
                  : _buildForm(),
            ),
          ),
        ),
      ),
    );
  }

  // ── "Check your email" state ──────────────────────────────────────────────

  Widget _buildConfirmationWaiting() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Icon
        Center(
          child: Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: kAccent.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(18),
            ),
            alignment: Alignment.center,
            child: const Icon(Icons.mark_email_unread_outlined,
                size: 34, color: kAccent),
          ),
        ),
        const SizedBox(height: 20),
        Text(
          'Check your email',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        Text(
          'We sent a confirmation link to\n$_confirmedEmail\n\n'
          'Tap the link in that email to activate your account, then come back here to sign in.',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!,
              textAlign: TextAlign.center,
              style: const TextStyle(color: kDanger, fontSize: 13)),
        ],
        const SizedBox(height: 28),
        _loading
            ? const Center(child: CircularProgressIndicator())
            : FilledButton.icon(
                onPressed: _resend,
                icon: const Icon(Icons.send, size: 18),
                label: const Text('Resend email'),
                style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(44)),
              ),
        const SizedBox(height: 10),
        OutlinedButton(
          onPressed: _backToSignIn,
          style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(44)),
          child: const Text('Back to sign in'),
        ),
      ],
    );
  }

  // ── Sign in / sign up form ────────────────────────────────────────────────

  Widget _buildForm() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Logo
        Center(
          child: Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              color: kAccent,
              borderRadius: BorderRadius.circular(14),
            ),
            alignment: Alignment.center,
            child: const Text(
              'J',
              style: TextStyle(
                color: Colors.white,
                fontSize: 26,
                fontWeight: FontWeight.w700,
                height: 1,
              ),
            ),
          ),
        ),
        const SizedBox(height: 20),
        Text(
          _isSignUp ? 'Create account' : 'Sign in',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 28),
        TextField(
          controller: _emailCtrl,
          decoration: const InputDecoration(labelText: 'Email'),
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.next,
          autofillHints: const [AutofillHints.email],
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _passCtrl,
          decoration: const InputDecoration(labelText: 'Password'),
          obscureText: true,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _submit(),
        ),
        if (_error != null) ...[
          const SizedBox(height: 10),
          Text(
            _error!,
            style: const TextStyle(color: kDanger, fontSize: 13),
          ),
        ],
        const SizedBox(height: 20),
        _loading
            ? const Center(child: CircularProgressIndicator())
            : FilledButton(
                onPressed: _submit,
                style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(44)),
                child: Text(_isSignUp ? 'Create account' : 'Sign in'),
              ),
        const SizedBox(height: 10),
        TextButton(
          onPressed: () => setState(() {
            _isSignUp = !_isSignUp;
            _error    = null;
          }),
          child: Text(
            _isSignUp
                ? 'Already have an account? Sign in'
                : 'No account? Create one',
            style: const TextStyle(fontSize: 13),
          ),
        ),
      ],
    );
  }
}

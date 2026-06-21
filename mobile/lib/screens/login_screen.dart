import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../main.dart';

// Supabase deep-link redirect URI — must also be registered in:
// Supabase Dashboard → Authentication → URL Configuration → Redirect URLs
const _kRedirectUrl = 'io.supabase.xsuqhjmonzcguedekqjt://login-callback/';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _passCtrl  = TextEditingController();
  bool   _loading        = false;
  bool   _googleLoading  = false;
  bool   _isSignUp       = false;
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

  // ── Email / password submit ───────────────────────────────────────────────

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
            _loading             = false;
            _waitingConfirmation = true;
            _confirmedEmail      = email;
          });
        }
      } else {
        await Supabase.instance.client.auth
            .signInWithPassword(email: email, password: password);
        // _AuthGate reacts to onAuthStateChange automatically.
      }
    } on AuthException catch (e) {
      String msg = e.message;
      if (msg.toLowerCase().contains('email not confirmed')) {
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

  // ── Google OAuth ──────────────────────────────────────────────────────────

  Future<void> _signInWithGoogle() async {
    setState(() { _googleLoading = true; _error = null; });
    try {
      await Supabase.instance.client.auth.signInWithOAuth(
        OAuthProvider.google,
        redirectTo: _kRedirectUrl,
      );
      // The browser opens; the result comes back via the deep link and
      // fires onAuthStateChange → _AuthGate navigates automatically.
      // We don't set _googleLoading = false here because the user leaves
      // the screen; if they cancel, onResume won't fire a state change,
      // so reset loading after a short delay.
      await Future.delayed(const Duration(seconds: 3));
      if (mounted) setState(() => _googleLoading = false);
    } on AuthException catch (e) {
      if (mounted) setState(() { _error = e.message; _googleLoading = false; });
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _googleLoading = false; });
    }
  }

  // ── Resend confirmation email ─────────────────────────────────────────────

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

  // ── Build ─────────────────────────────────────────────────────────────────

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

  // ── "Check your email" screen ─────────────────────────────────────────────

  Widget _buildConfirmationWaiting() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Center(
          child: Container(
            width: 64, height: 64,
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
        Text('Check your email',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        Text(
          'We sent a confirmation link to\n$_confirmedEmail\n\n'
          'Tap the link in that email to activate your account, '
          'then come back here to sign in.',
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

  // ── Sign-in / sign-up form ────────────────────────────────────────────────

  Widget _buildForm() {
    final isLoading = _loading || _googleLoading;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Logo
        Center(
          child: Container(
            width: 52, height: 52,
            decoration: BoxDecoration(
              color: kAccent,
              borderRadius: BorderRadius.circular(14),
            ),
            alignment: Alignment.center,
            child: const Text('J',
                style: TextStyle(
                    color: Colors.white,
                    fontSize: 26,
                    fontWeight: FontWeight.w700,
                    height: 1)),
          ),
        ),
        const SizedBox(height: 20),
        Text(
          _isSignUp ? 'Create account' : 'Sign in',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 28),

        // ── Google button ─────────────────────────────────────────────────
        _googleLoading
            ? const Center(child: CircularProgressIndicator())
            : OutlinedButton(
                onPressed: isLoading ? null : _signInWithGoogle,
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(44),
                  side: const BorderSide(color: kBorder, width: 1.5),
                  backgroundColor: kSurface,
                  foregroundColor: kFg,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8)),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _GoogleLogo(size: 20),
                    const SizedBox(width: 10),
                    Text(
                      _isSignUp
                          ? 'Continue with Google'
                          : 'Sign in with Google',
                      style: const TextStyle(
                          fontSize: 14, fontWeight: FontWeight.w500),
                    ),
                  ],
                ),
              ),

        // ── Divider ───────────────────────────────────────────────────────
        const SizedBox(height: 20),
        Row(children: [
          const Expanded(child: Divider()),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Text('or',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: kMuted)),
          ),
          const Expanded(child: Divider()),
        ]),
        const SizedBox(height: 20),

        // ── Email field ───────────────────────────────────────────────────
        TextField(
          controller: _emailCtrl,
          decoration: const InputDecoration(labelText: 'Email'),
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.next,
          autofillHints: const [AutofillHints.email],
          enabled: !isLoading,
        ),
        const SizedBox(height: 12),

        // ── Password field ────────────────────────────────────────────────
        TextField(
          controller: _passCtrl,
          decoration: const InputDecoration(labelText: 'Password'),
          obscureText: true,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _submit(),
          enabled: !isLoading,
        ),

        if (_error != null) ...[
          const SizedBox(height: 10),
          Text(_error!,
              style: const TextStyle(color: kDanger, fontSize: 13)),
        ],
        const SizedBox(height: 20),

        // ── Submit button ─────────────────────────────────────────────────
        _loading
            ? const Center(child: CircularProgressIndicator())
            : FilledButton(
                onPressed: isLoading ? null : _submit,
                style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(44)),
                child:
                    Text(_isSignUp ? 'Create account' : 'Sign in'),
              ),
        const SizedBox(height: 10),

        // ── Toggle sign-up / sign-in ──────────────────────────────────────
        TextButton(
          onPressed: isLoading
              ? null
              : () => setState(() {
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

// ── Google "G" logo (no external asset needed) ────────────────────────────────

class _GoogleLogo extends StatelessWidget {
  final double size;
  const _GoogleLogo({required this.size});

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      size: Size(size, size),
      painter: _GoogleLogoPainter(),
    );
  }
}

class _GoogleLogoPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final r = size.width / 2;
    final cx = r, cy = r;

    // Clip to circle
    canvas.clipPath(Path()..addOval(Rect.fromCircle(center: Offset(cx, cy), radius: r)));

    // White background
    canvas.drawCircle(
        Offset(cx, cy), r, Paint()..color = Colors.white);

    // Draw the four Google colour arcs using a path approach.
    // We draw 4 sectors that approximate the Google G logo.
    final strokeW = size.width * 0.18;
    final innerR  = r - strokeW;
    final rect    = Rect.fromCircle(center: Offset(cx, cy), radius: r - strokeW / 2);

    void arc(double startDeg, double sweepDeg, Color color) {
      final p = Paint()
        ..color       = color
        ..style       = PaintingStyle.stroke
        ..strokeWidth = strokeW
        ..strokeCap   = StrokeCap.butt;
      const d = 3.14159265358979 / 180;
      canvas.drawArc(rect, startDeg * d, sweepDeg * d, false, p);
    }

    // Red   top-right → bottom-right
    arc(-45,   135, const Color(0xFFEA4335));
    // Yellow bottom-right → bottom-left
    arc(90,    90,  const Color(0xFFFBBC05));
    // Green  bottom-left → top-left
    arc(180,   90,  const Color(0xFF34A853));
    // Blue   top-left → top-right (long arc)
    arc(270,   135, const Color(0xFF4285F4));

    // Blue horizontal bar (the G crossbar)
    final barPaint = Paint()
      ..color = const Color(0xFF4285F4)
      ..strokeWidth = strokeW
      ..strokeCap = StrokeCap.butt;
    canvas.drawLine(
      Offset(cx, cy),
      Offset(cx + innerR, cy),
      barPaint,
    );

    // White centre circle to punch out the middle
    canvas.drawCircle(
        Offset(cx, cy),
        innerR - strokeW / 2,
        Paint()..color = Colors.white);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

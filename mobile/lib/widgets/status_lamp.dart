import 'package:flutter/material.dart';

class StatusLamp extends StatefulWidget {
  final String color; // green | yellow | red | grey
  const StatusLamp({super.key, required this.color});

  @override
  State<StatusLamp> createState() => _StatusLampState();
}

class _StatusLampState extends State<StatusLamp>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    )..repeat(reverse: true);
    _anim = Tween<double>(begin: 0.6, end: 1.0).animate(
      CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Color get _mainColor => switch (widget.color) {
        'green'  => const Color(0xFF32CD32),
        'yellow' => const Color(0xFFF0B400),
        'red'    => const Color(0xFFDC3232),
        _        => const Color(0xFFA0A0A0),
      };

  @override
  Widget build(BuildContext context) {
    final isAnimated = widget.color == 'yellow';
    return AnimatedBuilder(
      animation: _anim,
      builder: (_, __) => Opacity(
        opacity: isAnimated ? _anim.value : 1.0,
        child: Container(
          width: 96,
          height: 96,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: _mainColor,
            boxShadow: [
              BoxShadow(
                color: _mainColor.withValues(alpha: 0.5),
                blurRadius: 24,
                spreadRadius: 6,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

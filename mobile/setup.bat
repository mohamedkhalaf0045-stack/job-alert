@echo off
echo == Job Alert Mobile Setup ==
echo.

where flutter >nul 2>&1
if %errorlevel% neq 0 (
    echo Flutter not found in PATH.
    echo Download and install from: https://docs.flutter.dev/get-started/install/windows
    echo Then re-run this script.
    pause
    exit /b 1
)

echo Flutter found. Running doctor...
flutter doctor --android-licenses
echo.

echo Installing dependencies...
flutter pub get
echo.

echo Done. To run the app:
echo   flutter run          ^(with device/emulator connected^)
echo   flutter build apk --release   ^(build APK for direct install^)
echo.
pause

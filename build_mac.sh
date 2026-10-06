#!/bin/bash
# Construit l'installateur macOS : Installateur/DeskMonitor-<version>-mac-<arm64|intel>.dmg
# À lancer SUR UN MAC (ou via GitHub Actions : .github/workflows/macos.yml).
set -euo pipefail
cd "$(dirname "$0")"

python3 -m pip install --upgrade --quiet psutil pillow certifi edge-tts pyinstaller pyobjc-framework-Cocoa pyobjc-framework-EventKit pyobjc-framework-Speech pyobjc-framework-AVFoundation
python3 make_icon.py
VERSION=$(python3 -c "from core import APP_VERSION; print(APP_VERSION)")
if [ "$(uname -m)" = "arm64" ]; then ARCH=arm64; else ARCH=intel; fi
echo "=== DeskMonitor $VERSION pour Mac ($ARCH) ==="

rm -rf build/dist build/work
python3 -m PyInstaller --noconfirm --clean --windowed --name DeskMonitor \
  --distpath build/dist --workpath build/work --specpath build \
  --icon "$PWD/assets/DeskMonitor.icns" --add-data "$PWD/assets/wallpapers:wallpapers" \
  --osx-bundle-identifier com.deskmonitor.app \
  --hidden-import objc --hidden-import AppKit --hidden-import Foundation --hidden-import EventKit --hidden-import Speech --hidden-import AVFoundation \
  --hidden-import certifi --collect-all edge_tts desk_monitor.py

APP=build/dist/DeskMonitor.app
PLIST="$APP/Contents/Info.plist"
# plutil -replace crée ou remplace la clé (et gère les apostrophes, contrairement à PlistBuddy -c)
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace CFBundleDisplayName -string "DeskMonitor" "$PLIST"
plutil -replace LSMinimumSystemVersion -string "11.0" "$PLIST"
plutil -replace NSHighResolutionCapable -bool true "$PLIST"
plutil -replace NSAppleEventsUsageDescription -string "DeskMonitor utilise « System Events » pour changer le fond d'écran et le Finder pour vider la corbeille." "$PLIST"
plutil -replace NSCalendarsUsageDescription -string "DeskMonitor affiche vos prochains événements dans la carte Agenda." "$PLIST"
plutil -replace NSCalendarsFullAccessUsageDescription -string "DeskMonitor affiche vos prochains événements dans la carte Agenda." "$PLIST"
plutil -replace NSRemindersUsageDescription -string "DeskMonitor affiche le nombre de vos rappels à faire dans la carte Agenda." "$PLIST"
plutil -replace NSRemindersFullAccessUsageDescription -string "DeskMonitor affiche le nombre de vos rappels à faire dans la carte Agenda." "$PLIST"
plutil -replace NSMicrophoneUsageDescription -string "L'assistant de DeskMonitor écoute votre question quand vous appuyez sur son raccourci." "$PLIST"
plutil -replace NSSpeechRecognitionUsageDescription -string "DeskMonitor transcrit vos commandes vocales, sur le Mac quand c'est possible." "$PLIST"
plutil -lint "$PLIST"

# signature locale (« ad hoc ») : indispensable sur les Mac Apple Silicon
codesign --force --deep --sign - "$APP"

STAGE=build/dmg
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "installer/Lisez-moi (Mac).txt" "$STAGE/"
mkdir -p Installateur
DMG="Installateur/DeskMonitor-$VERSION-mac-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "DeskMonitor $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "OK : $DMG"

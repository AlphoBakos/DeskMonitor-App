@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Construction de DeskMonitor ===

python -m pip install --upgrade --quiet psutil pillow pystray certifi winsdk edge-tts pyinstaller || goto :err
python make_icon.py || goto :err
for /f %%v in ('python -c "from core import APP_VERSION; print(APP_VERSION)"') do set VERSION=%%v
echo Version : %VERSION%

rem Application (mode dossier : démarrage rapide, moins de fausses alertes antivirus).
rem Les fichiers intermédiaires restent dans build\ : seul l'installateur est à partager.
python -m PyInstaller --noconfirm --clean --onedir --windowed --name DeskMonitor ^
  --distpath build\dist --workpath build\work --specpath build ^
  --icon "%CD%\assets\DeskMonitor.ico" --add-data "%CD%\assets\wallpapers;wallpapers" --add-data "%CD%\i18n_en.json;." ^
  --hidden-import pystray._win32 --collect-all winsdk --collect-all edge_tts desk_monitor.py || goto :err

set ISCC=
for %%p in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
  if exist %%p set ISCC=%%p
)
if not defined ISCC (
  echo Inno Setup est introuvable : installez-le avec  winget install JRSoftware.InnoSetup
  goto :err
)
if exist Installateur rmdir /s /q Installateur
%ISCC% /Q /DAppVersion=%VERSION% installer\DeskMonitor.iss || goto :err

echo.
echo OK : Installateur\DeskMonitor-Setup-%VERSION%.exe est pret.
echo C'est le SEUL fichier a donner : il s'installe sur n'importe quel PC Windows 10/11.
if not "%1"=="--no-pause" pause
exit /b 0

:err
echo ERREUR pendant la construction.
if not "%1"=="--no-pause" pause
exit /b 1

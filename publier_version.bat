@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Publie l'installateur sur GitHub pour que tous vos PC se mettent à jour automatiquement.
rem Prérequis : GitHub CLI (gh) connecté  ->  gh auth login
rem Usage     : publier_version.bat utilisateur/projet "Notes de version"

if "%~1"=="" (
  echo Usage : publier_version.bat utilisateur/projet "Notes de version"
  exit /b 1
)
for /f %%v in ('python -c "from core import APP_VERSION; print(APP_VERSION)"') do set VERSION=%%v
set SETUP=Installateur\DeskMonitor-Setup-%VERSION%.exe
if not exist "%SETUP%" (
  echo %SETUP% introuvable : lancez d'abord build.bat
  exit /b 1
)
set NOTES=%~2
if "%NOTES%"=="" set NOTES=DeskMonitor %VERSION%
gh release create v%VERSION% "%SETUP%" --repo %1 --title "DeskMonitor %VERSION%" --notes "%NOTES%" || exit /b 1
echo.
echo Version %VERSION% publiee. Les PC ou le depot "%1" est renseigne
echo (Parametres ^> General ^> Mises a jour) proposeront la mise a jour.

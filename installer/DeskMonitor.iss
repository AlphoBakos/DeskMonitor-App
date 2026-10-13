; Installateur DeskMonitor (Inno Setup 6) — compilé par build.bat
; Installation par utilisateur : aucun droit administrateur requis.

#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#define AppName "DeskMonitor"
#define AppExe "DeskMonitor.exe"

[Setup]
AppId={{6F1C2A57-3B8E-4C1D-9E0A-7D5B2F84C913}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\Installateur
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\DeskMonitor.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
MinVersion=10.0

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "autostart"; Description: "Lancer {#AppName} au démarrage de Windows"; GroupDescription: "Options :"
Name: "desktopicon"; Description: "Créer un raccourci sur le bureau"; GroupDescription: "Options :"; Flags: unchecked

[Files]
Source: "..\build\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; anciens fichiers de l'application (modules, fonds livrés) : la nouvelle version repart de zéro
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; pas de « skipifsilent » : après une mise à jour automatique (silencieuse), l'application redémarre
Filename: "{app}\{#AppExe}"; Description: "Lancer {#AppName} maintenant"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/im {#AppExe} /f"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{app}\{#AppExe}"; Parameters: "--show-icons"; Flags: runhidden waituntilterminated; RunOnceId: "ShowIcons"

[Code]
// Ferme l'application si elle tourne (installation par-dessus / mise à jour), et vérifie qu'elle est vraiment
// fermée AVANT de toucher aux fichiers : une instance lancée en administrateur résiste à taskkill, et
// l'installation supprimait alors l'ancien dossier sans pouvoir copier le nouveau (application cassée).
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code, I: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/im {#AppExe} /f', '', SW_HIDE, ewWaitUntilTerminated, Code);
  for I := 1 to 40 do
  begin
    if not CheckForMutexes('Local\DeskMonitor_SingleInstance') then
    begin
      Sleep(500);
      Result := '';
      exit;
    end;
    Sleep(250);
  end;
  Result := 'DeskMonitor est encore ouvert et n''a pas pu être fermé automatiquement ' +
            '(il a peut-être été lancé en administrateur). Quittez-le (icône près de l''horloge › Quitter), ' +
            'puis relancez l''installation. Rien n''a été modifié.';
end;

// Propose de supprimer aussi les réglages à la désinstallation.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('Supprimer aussi vos réglages (thème, profils, positions des widgets) ?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{userappdata}\{#AppName}'), True, True, True);
end;

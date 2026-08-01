; Inno Setup Skript fuer ZelaKueche.
; Erwartet einen fertigen PyInstaller-onedir-Build unter dist/ZelaKueche/ (siehe scripts/build_exe.py).
; Kompilieren: ISCC installer\zelakueche.iss  (erzeugt Output\ZelaKueche-Setup.exe)

#define MyAppName "ZelaKueche"
#define MyAppVersion "1.2.1"
#define MyAppPublisher "Kolping Zeltlager"
#define MyAppExeName "ZelaKueche.exe"
#define MySourceDist "..\dist\ZelaKueche"

[Setup]
AppId={{5C6E2B7C-6E5C-4E7B-9B0A-2D6E6F6B9C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Installation pro Benutzer, keine Admin-Rechte noetig.
DefaultDirName={autopf}\{#MyAppName}
PrivilegesRequired=lowest
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\Output
OutputBaseFilename=ZelaKueche-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\app\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySourceDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; Inno Setup script for the Elysium Master Application (LLD section 13;
; docs/IMPLEMENTATION_PLAN.md phase 8). Produces a double-click Windows
; installer -- a streamer never sees Python, pip, or a MongoDB connection
; string. Running the installer again over an existing install upgrades it
; in place (standard Inno Setup behavior; no separate upgrade path needed
; for this small trusted team per plan section 12).
;
; Build order:
;   1. pip install -e ".[build]"
;   2. pyinstaller packaging\ElysiumMasterApplication.spec --clean
;      (produces packaging\dist\ElysiumMasterApplication\)
;   3. iscc packaging\installer.iss
;      (produces packaging\installer_output\ElysiumMasterApplication-Setup.exe)
;
; AppId is fixed forever once first released -- changing it would make Inno
; Setup treat future versions as a different, separately-installed program
; instead of an in-place upgrade.

#define MyAppName "Elysium Master Application"
#define MyAppVersion "1.0.12"
#define MyAppPublisher "Elysium"
#define MyAppExeName "ElysiumMasterApplication.exe"

[Setup]
AppId={{B2C961B6-AB6B-4314-8C2F-C56F5BB144A5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=ElysiumMasterApplication-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=app_icon.ico
WizardStyle=modern
; No credentials, no MongoDB URI, no Python are ever prompted for or
; embedded here -- per-machine setup (the real Atlas connection) happens
; the first time the installed app runs, via its own .env/keyring flow.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Everything PyInstaller collected -- the app, its bundled Python runtime,
; and all dependencies. No user data ships here: the local card database,
; Scryfall cache, and image cache are all created at first run under
; %LOCALAPPDATA%\ElysiumMasterApp (elysium/local_card/paths.py).
Source: "dist\ElysiumMasterApplication\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

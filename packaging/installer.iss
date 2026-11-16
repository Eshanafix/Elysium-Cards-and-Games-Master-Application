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
#define MyAppVersion "1.0.21"
#define MyAppPublisher "Elysium"
#define MyAppExeName "ElysiumMasterApplication.exe"

[Setup]
AppId={{B2C961B6-AB6B-4314-8C2F-C56F5BB144A5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install, no admin rights required -- team members are not
; guaranteed to be admins on their own machines. {autopf}/{autodesktop}
; below already resolve to the per-user Program-Files-equivalent and the
; user's own desktop (rather than the machine-wide ones) once this is set;
; no other path needs to change. This also means the uninstall registry
; entry lives in HKCU, separate from any earlier admin-mode install of this
; same AppId -- see docs/IMPLEMENTATION_PLAN.md packaging notes.
PrivilegesRequired=lowest
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
;
; CloseApplications: a safety net for the plain manual/interactive case --
; if someone double-clicks a freshly downloaded installer while the app
; happens to still be open, Restart Manager closes it rather than failing
; outright. NOT relied on for in-app self-update (elysium/services/
; self_update_service.py) -- empirically, on real hardware, Restart
; Manager's "ask this Qt app to close" request is unreliable (confirmed
; live: sometimes closes it within ~10s, sometimes never closes it at all
; even after 90+s, with no code difference between runs). The self-updater
; instead quits the app itself (code it fully controls, consistently fast)
; immediately after launching the installer, so by the time the installer
; gets to the file-copy step there's usually nothing left to close.
;
; RestartApplications is deliberately NOT set -- same unreliability
; (confirmed live: never observed it actually relaunch the app within the
; same window CloseApplications needed to close it). The [Run] entry
; below (postinstall, without skipifsilent) is what reliably relaunches
; the app after any install, interactive or silent.
CloseApplications=yes

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
; skipifsilent deliberately removed -- in-app self-update (elysium/
; services/self_update_service.py) runs this installer /VERYSILENT and
; needs this launch to actually fire afterward, which skipifsilent exists
; specifically to prevent. A normal interactive install still gets the
; same "Launch" checkbox on the finish page either way (that page -- and
; whether it's even shown -- is controlled by "postinstall" plus the
; wizard's own ShowLanguageDialog, not by skipifsilent).
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall

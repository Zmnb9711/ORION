#define MyAppName "ORION Alpha"
#define MyAppVersion "0.2.0-alpha"
#define MyAppPublisher "ORION"
#define MyLauncherExe "Launcher\ORION-Launcher.exe"
#define MyCoreExe "Core\ORION-Core.exe"
#define MyUninstallerHelperExe "Uninstaller\ORION-Uninstall.exe"

[Setup]
AppId={{6E4CA1C5-4E77-42CE-9E6B-A6D1124B09E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ORION
DefaultGroupName=ORION
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=ORION-Alpha-0.2-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyLauncherExe}
#if FileExists("..\branding\orion.ico")
SetupIconFile=..\branding\orion.ico
#endif

[InstallDelete]
; An Alpha upgrade is a payload replacement, not a blind overwrite. Runtime/STT
; under LocalAppData is intentionally preserved, but every shipped product file
; is removed before the new payload is copied.
Type: filesandordirs; Name: "{app}\Core"
Type: filesandordirs; Name: "{app}\Launcher"
Type: filesandordirs; Name: "{app}\Uninstaller"
Type: filesandordirs; Name: "{app}\Integration"
; Remove shortcuts created by earlier Alpha layouts.
Type: files; Name: "{autoprograms}\ORION Core.lnk"
Type: files; Name: "{autoprograms}\ORION.lnk"
Type: files; Name: "{autodesktop}\ORION.lnk"

[Files]
Source: "..\dist-product\Core\*"; DestDir: "{app}\Core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist-product\Launcher\*"; DestDir: "{app}\Launcher"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist-product\Uninstaller\*"; DestDir: "{app}\Uninstaller"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist-product\Integration\*"; DestDir: "{app}\Integration"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{localappdata}\ORION\runtime"
Name: "{localappdata}\ORION\runtime\logs"
Name: "{localappdata}\ORION\runtime\diagnostics"
Name: "{localappdata}\ORION\runtime\updates"

[Icons]
Name: "{autoprograms}\ORION"; Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"
Name: "{autodesktop}\ORION"; Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"; Description: "Launch ORION"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM ORION-Launcher.exe >nul 2>&1 || exit /B 0"; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM ORION-Core.exe >nul 2>&1 || exit /B 0"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\ORION"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  // Stop every old ORION process before InstallDelete or file replacement.
  // This makes an upgrade deterministic and prevents a new Launcher from
  // attaching to an old in-memory Core.
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM ORION-Launcher.exe >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM ORION-Core.exe >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

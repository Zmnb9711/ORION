#define MyAppName "ORION Alpha"
#define MyAppVersion "0.2.0-alpha"
#define MyAppPublisher "ORION"
#define MyLauncherExe "Launcher\ORION-Launcher.exe"
#define MyCoreExe "Core\ORION-Core.exe"
#ifndef ProductSourceDir
#define ProductSourceDir "..\dist-product"
#endif

[Setup]
AppId={{6E4CA1C5-4E77-42CE-9E6B-A6D1124B09E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ORION
DefaultGroupName=ORION
DisableProgramGroupPage=yes
#ifndef InstallerOutputDir
#define InstallerOutputDir "..\dist-installer"
#endif
OutputDir={#InstallerOutputDir}
OutputBaseFilename=ORION-Alpha-0.2-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyLauncherExe}
CloseApplications=yes
RestartApplications=no
#if FileExists("..\branding\orion.ico")
SetupIconFile=..\branding\orion.ico
#endif

[Files]
Source: "{#ProductSourceDir}\Core\*"; DestDir: "{app}\Core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProductSourceDir}\Launcher\*"; DestDir: "{app}\Launcher"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProductSourceDir}\Integration\*"; DestDir: "{app}\Integration"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{localappdata}\ORION\runtime"
Name: "{localappdata}\ORION\runtime\logs"
Name: "{localappdata}\ORION\runtime\diagnostics"
Name: "{localappdata}\ORION\runtime\updates"
Name: "{localappdata}\ORION\communication-profiles"

[InstallDelete]
; Upgrade migration: remove only known ORION-managed legacy voice paths.
Type: filesandordirs; Name: "{app}\Voice"
Type: filesandordirs; Name: "{localappdata}\ORION\runtime\voice"
Type: filesandordirs; Name: "{localappdata}\ORION\runtime\stt\whisper.cpp"

[Icons]
Name: "{autoprograms}\ORION"; Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"
Name: "{autoprograms}\ORION Core"; Filename: "{app}\{#MyCoreExe}"; WorkingDir: "{app}\Core"
Name: "{autodesktop}\ORION"; Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"; Description: "Launch ORION"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM ORION-Launcher.exe >nul 2>&1 || exit /B 0"; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM ORION-Core.exe >nul 2>&1 || exit /B 0"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyLauncherExe}"; Parameters: "--clear-voice-credentials"; Flags: runhidden waituntilterminated skipifdoesntexist

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\ORION\runtime"

[Code]
procedure KillProcessByImage(const ImageName: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM ' + ImageName + ' >nul 2>&1 || exit /B 0', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  { An alpha update is explicitly supported in-place. ORION Core intentionally
    survives normal Launcher window closes, so Setup must own the upgrade
    boundary and stop every product process before replacing binaries. }
  KillProcessByImage('ORION-Launcher.exe');
  KillProcessByImage('ORION-Core.exe');
  Sleep(400);
  Result := '';
end;

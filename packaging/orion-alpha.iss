#define MyAppName "ORION Alpha"
#define MyAppVersion "0.2.0-alpha"
#define MyAppPublisher "ORION"
#define MyLauncherExe "Launcher\ORION-Launcher.exe"
#define MyCoreExe "Core\ORION-Core.exe"

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

[Files]
Source: "..\dist-product\Core\*"; DestDir: "{app}\Core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist-product\Launcher\*"; DestDir: "{app}\Launcher"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist-product\Integration\*"; DestDir: "{app}\Integration"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{localappdata}\ORION\runtime"
Name: "{localappdata}\ORION\runtime\logs"
Name: "{localappdata}\ORION\runtime\diagnostics"
Name: "{localappdata}\ORION\runtime\updates"

[Icons]
Name: "{autoprograms}\ORION"; Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"
Name: "{autoprograms}\ORION Core"; Filename: "{app}\{#MyCoreExe}"; WorkingDir: "{app}\Core"
Name: "{autodesktop}\ORION"; Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyLauncherExe}"; WorkingDir: "{app}\Launcher"; Description: "Launch ORION"; Flags: nowait postinstall skipifsilent

#define MyAppName "ORION Alpha"
#define MyAppVersion "0.1.0-alpha"
#define MyAppPublisher "ORION"
#define MyAppExeName "ORION.exe"

[Setup]
AppId={{6E4CA1C5-4E77-42CE-9E6B-A6D1124B09E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ORION Alpha
DefaultGroupName=ORION Alpha
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=ORION-Alpha-0.1-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\ORION\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ORION Alpha"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--desktop"
Name: "{autodesktop}\ORION Alpha"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--desktop"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--desktop"; Description: "Launch ORION Alpha"; Flags: nowait postinstall skipifsilent

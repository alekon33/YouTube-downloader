#ifndef AppVersion
  #error AppVersion must be supplied by scripts\build_installer.ps1
#endif

#define AppName "VideoDownloader"
#define AppExeName "VideoDownloader.exe"
#define AppId "{{F94FD45C-8927-4DFE-A73C-E691075E21A8}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=VideoDownloader contributors
AppCopyright=Copyright (c) 2026 VideoDownloader contributors
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0.17763
OutputDir=output
OutputBaseFilename=VideoDownloaderSetup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no
VersionInfoVersion={#AppVersion}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\VideoDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent


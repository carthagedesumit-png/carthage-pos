#define MyAppName "Carthage Business Operating System"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Carthage Systems"
#define MyAppExeName "CarthagePOS.exe"
#ifndef MySourceRoot
  #define MySourceRoot "..\dist"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "output"
#endif

[Setup]
AppId={{9A81751F-18D8-4B90-9237-9B79845CB945}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Carthage Business Operating System
DefaultGroupName=Carthage Business Operating System
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir={#MyOutputDir}
OutputBaseFilename=CBOS-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#MySourceRoot}\CarthagePOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MySourceRoot}\CarthagePOSDeployment\*"; DestDir: "{app}\deployment"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\carthage-pos.ico"; DestDir: "{app}\assets"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Carthage Business Operating System"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Repair CBOS"; Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "repair --install-dir ""{app}"""; WorkingDir: "{app}"
Name: "{autodesktop}\Carthage Business Operating System"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "configure --install-dir ""{app}"""; Description: "Configure or upgrade CBOS"; Flags: postinstall waituntilterminated skipifsilent

[UninstallRun]
Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "uninstall --install-dir ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "CarthagePOSRuntimeCleanup"

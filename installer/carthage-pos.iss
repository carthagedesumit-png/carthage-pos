#define MyAppName "Carthage POS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Carthage Systems"
#define MyAppExeName "CarthagePOS.exe"

[Setup]
AppId={{9A81751F-18D8-4B90-9237-9B79845CB945}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Carthage POS
DefaultGroupName=Carthage POS
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir=output
OutputBaseFilename=CarthagePOS-Setup-{#MyAppVersion}
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
Source: "..\dist\CarthagePOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\CarthagePOSDeployment\*"; DestDir: "{app}\deployment"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\carthage-pos.ico"; DestDir: "{app}\assets"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Carthage POS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Repair Carthage POS"; Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "repair --install-dir ""{app}"""; WorkingDir: "{app}"
Name: "{autodesktop}\Carthage POS"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "configure --install-dir ""{app}"""; Description: "Configure or upgrade Carthage POS"; Flags: postinstall waituntilterminated skipifsilent

[UninstallRun]
Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "uninstall --install-dir ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "CarthagePOSRuntimeCleanup"

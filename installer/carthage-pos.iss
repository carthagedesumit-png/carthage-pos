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
Source: "{#MySourceRoot}\CarthagePOSUpgradeVerifier.exe"; Flags: dontcopy
Source: "assets\carthage-pos.ico"; DestDir: "{app}\assets"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Carthage Business Operating System"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Repair CBOS"; Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "repair --install-dir ""{app}"""; WorkingDir: "{app}"
Name: "{autodesktop}\Carthage Business Operating System"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[UninstallRun]
Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "uninstall --install-dir ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "CarthagePOSRuntimeCleanup"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch CBOS"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent; Check: ShouldOfferLaunch

[Code]
#include "password_file_contract.iss"
var
  BusinessPage: TInputQueryWizardPage;
  AdminPage: TInputQueryWizardPage;
  OperationsPage: TInputQueryWizardPage;
  SilentAdminPassword: String;

function QuoteArg(Value: String): String;
var
  Escaped: String;
begin
  Escaped := Value;
  StringChangeEx(Escaped, '"', '\"', False);
  Result := '"' + Escaped + '"';
end;

function RuntimeRoot(): String;
begin
  Result := ExpandConstant('{param:CBOSRuntimeRoot|}');
  if Trim(Result) = '' then begin
    Result := ExpandConstant('{commonappdata}\Carthage POS');
  end;
end;

function SetupValue(Page: TInputQueryWizardPage; Index: Integer; ParamName: String): String;
begin
  Result := ExpandConstant('{param:' + ParamName + '|}');
  if Trim(Result) = '' then begin
    Result := Page.Values[Index];
  end;
end;

function RequireSilentParam(ParamName: String; LabelText: String): Boolean;
begin
  Result := Trim(ExpandConstant('{param:' + ParamName + '|}')) <> '';
  if not Result then begin
    Log('ERROR: ' + LabelText + ' is required for silent CBOS installation.');
    MsgBox(LabelText + ' is required for silent CBOS installation.', mbError, MB_OK);
  end;
end;

function LoadSilentAdminPassword: Boolean;
var
  PasswordFile: String;
  PasswordLines: TArrayOfString;
begin
  Result := False;
  PasswordFile := ExpandConstant('{param:CBOSAdminPasswordFile|}');
  if Trim(PasswordFile) = '' then begin
    Log('ERROR: Administrator password file is required for silent CBOS installation.');
    MsgBox('Administrator password file is required for silent CBOS installation.', mbError, MB_OK);
    exit;
  end;
  if not LoadStringsFromFile(PasswordFile, PasswordLines) then begin
    Log('ERROR: Administrator password file could not be read for silent CBOS installation.');
    MsgBox('Administrator password file could not be read. Verify the path and access permissions.', mbError, MB_OK);
    exit;
  end;
  DeleteFile(PasswordFile);
  if (GetArrayLength(PasswordLines) <> 1) or (Trim(PasswordLines[0]) = '') then begin
    Log('ERROR: Administrator password file must contain exactly one non-empty line.');
    MsgBox('Administrator password file must contain exactly one non-empty line.', mbError, MB_OK);
    exit;
  end;
  SilentAdminPassword := PasswordLines[0];
  Result := True;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if WizardSilent() then begin
    Result :=
      RequireSilentParam('CBOSBusiness', 'Business name') and
      RequireSilentParam('CBOSStore', 'Store name') and
      RequireSilentParam('CBOSAdminUser', 'Administrator username') and
      LoadSilentAdminPassword() and
      RequireSilentParam('CBOSAdminFullName', 'Administrator full name') and
      RequireSilentParam('CBOSCurrency', 'Currency') and
      RequireSilentParam('CBOSTaxRate', 'Tax rate') and
      RequireSilentParam('CBOSTimezone', 'Timezone') and
      RequireSilentParam('CBOSDeploymentType', 'Deployment type') and
      RequireSilentParam('CBOSPrinter', 'Receipt printer');
  end;
end;

procedure InitializeWizard;
begin
  BusinessPage := CreateInputQueryPage(
    wpSelectDir,
    'CBOS business setup',
    'Enter the business identity for this installation.',
    'These values are stored in ProgramData with the deployment configuration.'
  );
  BusinessPage.Add('Business name:', False);
  BusinessPage.Add('Store name:', False);
  BusinessPage.Values[0] := ExpandConstant('{param:CBOSBusiness|}');
  BusinessPage.Values[1] := 'Main Store';
  if Trim(ExpandConstant('{param:CBOSStore|}')) <> '' then begin
    BusinessPage.Values[1] := ExpandConstant('{param:CBOSStore|}');
  end;

  AdminPage := CreateInputQueryPage(
    BusinessPage.ID,
    'CBOS administrator',
    'Create the first administrator account.',
    'Choose a strong password. The password is used only to initialize the database and is not written to configuration files.'
  );
  if FileExists(RuntimeRoot() + '\config\deployment.json') then begin
    AdminPage.Add('Existing administrator username:', False);
    AdminPage.Add('Current existing administrator password:', True);
  end else begin
    AdminPage.Add('New administrator username:', False);
    AdminPage.Add('New administrator password:', True);
  end;
  AdminPage.Add('Administrator full name:', False);
  AdminPage.Values[0] := 'admin';
  if Trim(ExpandConstant('{param:CBOSAdminUser|}')) <> '' then begin
    AdminPage.Values[0] := ExpandConstant('{param:CBOSAdminUser|}');
  end;
  AdminPage.Values[1] := SilentAdminPassword;
  AdminPage.Values[2] := ExpandConstant('{param:CBOSAdminFullName|}');

  OperationsPage := CreateInputQueryPage(
    AdminPage.ID,
    'CBOS operating settings',
    'Confirm local operating defaults.',
    'Mutable application data will be stored under ProgramData.'
  );
  OperationsPage.Add('Currency:', False);
  OperationsPage.Add('Tax rate as decimal:', False);
  OperationsPage.Add('Timezone:', False);
  OperationsPage.Add('Receipt printer (none/58mm/80mm/generic):', False);
  OperationsPage.Add('Deployment type (desktop/standalone/network):', False);
  OperationsPage.Values[0] := 'USD';
  OperationsPage.Values[1] := '0';
  OperationsPage.Values[2] := 'UTC';
  OperationsPage.Values[3] := 'none';
  OperationsPage.Values[4] := 'desktop';
  if Trim(ExpandConstant('{param:CBOSCurrency|}')) <> '' then begin
    OperationsPage.Values[0] := ExpandConstant('{param:CBOSCurrency|}');
  end;
  if Trim(ExpandConstant('{param:CBOSTaxRate|}')) <> '' then begin
    OperationsPage.Values[1] := ExpandConstant('{param:CBOSTaxRate|}');
  end;
  if Trim(ExpandConstant('{param:CBOSTimezone|}')) <> '' then begin
    OperationsPage.Values[2] := ExpandConstant('{param:CBOSTimezone|}');
  end;
  if Trim(ExpandConstant('{param:CBOSPrinter|}')) <> '' then begin
    OperationsPage.Values[3] := ExpandConstant('{param:CBOSPrinter|}');
  end;
  if Trim(ExpandConstant('{param:CBOSDeploymentType|}')) <> '' then begin
    OperationsPage.Values[4] := ExpandConstant('{param:CBOSDeploymentType|}');
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = BusinessPage.ID then begin
    if (Trim(BusinessPage.Values[0]) = '') or (Trim(BusinessPage.Values[1]) = '') then begin
      MsgBox('Business name and store name are required.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = AdminPage.ID then begin
    if (Trim(AdminPage.Values[0]) = '') or (Trim(AdminPage.Values[1]) = '') or (Trim(AdminPage.Values[2]) = '') then begin
      MsgBox('Administrator username, password, and full name are required.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = OperationsPage.ID then begin
    if (Trim(OperationsPage.Values[0]) = '') or (Trim(OperationsPage.Values[1]) = '') or
       (Trim(OperationsPage.Values[2]) = '') or (Trim(OperationsPage.Values[3]) = '') or
       (Trim(OperationsPage.Values[4]) = '') then begin
      MsgBox('All operating settings are required.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure RunDeploymentConfiguration;
var
  ResultCode: Integer;
  Arguments: String;
  Runtime: String;
  PasswordFile: String;
begin
  Runtime := RuntimeRoot();
  ForceDirectories(Runtime + '\config');
  ForceDirectories(Runtime + '\data');
  ForceDirectories(Runtime + '\backups');

  PasswordFile := ExpandConstant('{tmp}\cbos-admin-password.input');
  if not WriteAdminPasswordFile(
    PasswordFile,
    AdminPage.Values[1]
  ) then begin
    RaiseException('CBOS could not create its temporary administrator password input.');
  end;

  Arguments :=
    'configure' +
    ' --install-dir ' + QuoteArg(ExpandConstant('{app}')) +
    ' --business-name ' + QuoteArg(SetupValue(BusinessPage, 0, 'CBOSBusiness')) +
    ' --store-name ' + QuoteArg(SetupValue(BusinessPage, 1, 'CBOSStore')) +
    ' --admin-username ' + QuoteArg(SetupValue(AdminPage, 0, 'CBOSAdminUser')) +
    ' --admin-password-file ' + QuoteArg(PasswordFile) +
    ' --admin-full-name ' + QuoteArg(SetupValue(AdminPage, 2, 'CBOSAdminFullName')) +
    ' --config-dir ' + QuoteArg(Runtime + '\config') +
    ' --database-path ' + QuoteArg(Runtime + '\data\carthage-pos.db') +
    ' --backup-path ' + QuoteArg(Runtime + '\backups') +
    ' --currency ' + QuoteArg(SetupValue(OperationsPage, 0, 'CBOSCurrency')) +
    ' --tax-rate ' + QuoteArg(SetupValue(OperationsPage, 1, 'CBOSTaxRate')) +
    ' --timezone ' + QuoteArg(SetupValue(OperationsPage, 2, 'CBOSTimezone')) +
    ' --receipt-printer ' + QuoteArg(SetupValue(OperationsPage, 3, 'CBOSPrinter')) +
    ' --deployment-type ' + QuoteArg(SetupValue(OperationsPage, 4, 'CBOSDeploymentType'));

  try
    if not Exec(ExpandConstant('{app}\deployment\CarthagePOSDeployment.exe'), Arguments,
                ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) then begin
      RaiseException('CBOS deployment could not be started.');
    end;
    if ResultCode <> 0 then begin
      RaiseException('CBOS deployment failed. Setup cannot continue.');
    end;
  finally
    DeleteFile(PasswordFile);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  PasswordFile: String;
  Arguments: String;
  Verifier: String;
begin
  Result := '';
  { Verify preserved credentials before [Files] replaces any installed binary. }
  if not FileExists(RuntimeRoot() + '\config\deployment.json') then begin
    exit;
  end;
  PasswordFile := ExpandConstant('{tmp}\cbos-upgrade-password.input');
  try
    if not WriteAdminPasswordFile(PasswordFile, AdminPage.Values[1]) then begin
      Result := 'CBOS could not create its temporary upgrade credential input.';
      exit;
    end;
    ExtractTemporaryFile('CarthagePOSUpgradeVerifier.exe');
    Verifier := ExpandConstant('{tmp}\CarthagePOSUpgradeVerifier.exe');
    Arguments :=
      'verify-upgrade-credentials' +
      ' --install-dir ' + QuoteArg(ExpandConstant('{app}')) +
      ' --username ' + QuoteArg(SetupValue(AdminPage, 0, 'CBOSAdminUser')) +
      ' --password-file ' + QuoteArg(PasswordFile);
    if not Exec(Verifier, Arguments, ExpandConstant('{tmp}'), SW_HIDE,
                ewWaitUntilTerminated, ResultCode) then begin
      Result := 'CBOS upgrade credential verification could not be started.';
    end else if ResultCode = 10 then begin
      Result := 'Existing administrator username is missing. No application files were replaced.';
    end else if ResultCode = 11 then begin
      Result := 'Current administrator password input is missing or invalid. No application files were replaced.';
    end else if ResultCode = 12 then begin
      Result := 'Installed ProgramData configuration was not found. No application files were replaced.';
    end else if ResultCode = 13 then begin
      Result := 'The configured installed database was not found. No application files were replaced.';
    end else if ResultCode = 14 then begin
      Result := 'The existing administrator username was not found. No application files were replaced.';
    end else if ResultCode = 15 then begin
      Result := 'The existing administrator account is inactive. No application files were replaced.';
    end else if ResultCode = 16 then begin
      Result := 'The existing administrator account is locked. No application files were replaced.';
    end else if ResultCode = 17 then begin
      Result := 'The current existing administrator password did not match. No application files were replaced.';
    end else if ResultCode = 18 then begin
      Result := 'The supplied account is not an administrator. No application files were replaced.';
    end else if ResultCode <> 0 then begin
      Result := 'The extracted upgrade verifier could not load its runtime. No application files were replaced.';
    end;
  finally
    DeleteFile(PasswordFile);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    RunDeploymentConfiguration();
  end;
end;

function ShouldOfferLaunch(): Boolean;
begin
  Result := False;
  if not WizardSilent() then begin
    Result := True;
  end;
end;

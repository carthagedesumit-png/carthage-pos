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

[UninstallRun]
Filename: "{app}\deployment\CarthagePOSDeployment.exe"; Parameters: "uninstall --install-dir ""{app}"""; Flags: runhidden waituntilterminated; RunOnceId: "CarthagePOSRuntimeCleanup"

[Code]
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
  AdminPage.Add('Administrator username:', False);
  AdminPage.Add('Administrator password:', True);
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
  if not SaveStringToFile(
    PasswordFile,
    AdminPage.Values[1],
    False
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

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    RunDeploymentConfiguration();
    if not WizardSilent() then begin
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), '', ExpandConstant('{app}'), SW_SHOWNORMAL,
           ewNoWait, ResultCode);
    end;
  end;
end;

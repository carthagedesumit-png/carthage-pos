#define ContractOutputDir ".\output"

[Setup]
AppId={{A38F6690-801A-4AA6-8663-CF38BEFA6A3D}
AppName=CBOS Password Contract Harness
AppVersion=1
DefaultDirName={tmp}\CBOSPasswordContractHarness
Uninstallable=no
OutputDir={#ContractOutputDir}
OutputBaseFilename=CBOS-Password-Contract-Harness
PrivilegesRequired=lowest

[Code]
#include "password_file_contract.iss"

function InitializeSetup(): Boolean;
var
  OutputPath: String;
begin
  OutputPath := ExpandConstant('{param:ContractOutput|}');
  if OutputPath = '' then begin
    RaiseException('ContractOutput is required.');
  end;
  if not WriteAdminPasswordFile(OutputPath, 'Harness-Only 42!') then begin
    RaiseException('Contract output could not be written.');
  end;
  Result := False;
end;

function WriteAdminPasswordFile(Path: String; Password: String): Boolean;
begin
  { Inno Unicode SaveStringToFile emits UTF-8 with a BOM. The deployment
    consumer deliberately accepts that exact representation. }
  Result := SaveStringToFile(Path, Password, False);
end;

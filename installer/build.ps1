param(
    [string]$Python = "python",
    [string]$InnoSetupCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Version = (& $Python "scripts\validate_release.py" version).Trim()
$VersionFile = Join-Path $Root "build\version_info.txt"
& $Python "scripts\validate_release.py" pyinstaller-version-file $VersionFile | Out-Null
& $Python -m PyInstaller --version | Out-Null
$RuntimeAssetJson = & $Python -m app.deployment.runtime_assets --root $Root --format json
if ($LASTEXITCODE -ne 0) {
    throw "Runtime asset validation failed before packaging."
}
[string[]]$RuntimeAssetArguments = $RuntimeAssetJson | ConvertFrom-Json

$Common = @(
    "--noconfirm", "--clean", "--onedir",
    "--version-file", $VersionFile
)
$Common += $RuntimeAssetArguments
$Icon = "installer\assets\carthage-pos.ico"
if (Test-Path $Icon) {
    $Common += @("--icon", $Icon)
}

& $Python -m PyInstaller @Common --name "CarthagePOS" "main.py"
& $Python -m PyInstaller @Common --name "CarthagePOSDeployment" "deployment_cli.py"

if (-not $SkipInstaller) {
    if (-not (Test-Path $InnoSetupCompiler)) {
        throw "Inno Setup 6 compiler was not found: $InnoSetupCompiler"
    }
    & $InnoSetupCompiler "/DMyAppVersion=""$Version""" "installer\carthage-pos.iss"
}

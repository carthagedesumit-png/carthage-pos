param(
    [string]$Python = "python",
    [string]$InnoSetupCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

& $Python -m PyInstaller --version | Out-Null

$Common = @(
    "--noconfirm", "--clean", "--onedir",
    "--version-file", "installer\version_info.txt"
)
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
    & $InnoSetupCompiler "installer\carthage-pos.iss"
}

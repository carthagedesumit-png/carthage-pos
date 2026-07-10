param(
    [string]$Python = "python",
    [string]$ReleaseRoot = "release",
    [string]$InnoSetupCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Version = (& $Python "scripts\validate_release.py" version).Trim()
if (-not $Version) {
    throw "Unable to determine authoritative CBOS version."
}

$Commit = (& git rev-parse --short=12 HEAD).Trim()
$BuildRoot = Join-Path $Root "build\rc"
$ReleaseDir = Join-Path (Join-Path $Root $ReleaseRoot) "CBOS-$Version"
$VersionFile = Join-Path $BuildRoot "version_info.txt"
$PyInstallerWork = Join-Path $BuildRoot "pyinstaller"
$InstallerOutput = Join-Path $ReleaseDir "installer"

if (Test-Path $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
if (Test-Path $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BuildRoot, $ReleaseDir, $InstallerOutput | Out-Null

& $Python -m unittest discover -s tests -v
& git diff --check
& $Python "scripts\validate_release.py" pyinstaller-version-file $VersionFile | Out-Null
& $Python -m PyInstaller --version | Out-Null

$Common = @(
    "--noconfirm", "--clean", "--onedir",
    "--version-file", $VersionFile,
    "--distpath", $ReleaseDir,
    "--workpath", $PyInstallerWork,
    "--specpath", $BuildRoot,
    "--add-data", "app\dashboard\templates;app\dashboard\templates",
    "--add-data", "app\dashboard\static;app\dashboard\static"
)

$Icon = "installer\assets\carthage-pos.ico"
if (Test-Path $Icon) {
    $Common += @("--icon", $Icon)
}

& $Python -m PyInstaller @Common --name "CarthagePOS" "main.py"
& $Python -m PyInstaller @Common --name "CarthagePOSDeployment" "deployment_cli.py"

$InstallerBuilt = $false
if (-not $SkipInstaller) {
    if (-not (Test-Path $InnoSetupCompiler)) {
        throw "Inno Setup 6 compiler was not found: $InnoSetupCompiler"
    }
    & $InnoSetupCompiler `
        "/DMyAppVersion=""$Version""" `
        "/DMySourceRoot=""$ReleaseDir""" `
        "/DMyOutputDir=""$InstallerOutput""" `
        "installer\carthage-pos.iss"
    $InstallerBuilt = $true
}

$EvidenceArgs = @(
    "scripts\validate_release.py", "evidence",
    "--release-dir", $ReleaseDir,
    "--source-commit", $Commit,
    "--require-executables"
)
if ($InstallerBuilt) {
    $EvidenceArgs += "--require-installer"
}
& $Python @EvidenceArgs

Write-Host "CBOS RC build complete: $ReleaseDir"

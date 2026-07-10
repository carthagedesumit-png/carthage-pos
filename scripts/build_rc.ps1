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

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

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

Invoke-Native "Unit tests" $Python @("-m", "unittest", "discover", "-s", "tests", "-v")
Invoke-Native "Whitespace validation" "git" @("diff", "--check")
Invoke-Native "PyInstaller version metadata generation" $Python @("scripts\validate_release.py", "pyinstaller-version-file", $VersionFile)
Invoke-Native "PyInstaller prerequisite check" $Python @("-m", "PyInstaller", "--version")

$DashboardTemplates = (Resolve-Path "app\dashboard\templates").Path
$DashboardStatic = (Resolve-Path "app\dashboard\static").Path
$MainEntry = (Resolve-Path "main.py").Path
$DeploymentEntry = (Resolve-Path "deployment_cli.py").Path

$Common = @(
    "--noconfirm", "--clean", "--onedir",
    "--version-file", $VersionFile,
    "--distpath", $ReleaseDir,
    "--workpath", $PyInstallerWork,
    "--specpath", $BuildRoot,
    "--add-data", "$DashboardTemplates;app\dashboard\templates",
    "--add-data", "$DashboardStatic;app\dashboard\static"
)

$Icon = "installer\assets\carthage-pos.ico"
if (Test-Path $Icon) {
    $Common += @("--icon", $Icon)
}

Invoke-Native "CarthagePOS PyInstaller build" $Python (@("-m", "PyInstaller") + $Common + @("--name", "CarthagePOS", $MainEntry))
Invoke-Native "CarthagePOSDeployment PyInstaller build" $Python (@("-m", "PyInstaller") + $Common + @("--name", "CarthagePOSDeployment", $DeploymentEntry))

$AppPayload = Join-Path $ReleaseDir "CarthagePOS"
$DeploymentPayload = Join-Path $ReleaseDir "CarthagePOSDeployment"
$AppExe = Join-Path $AppPayload "CarthagePOS.exe"
$DeploymentExe = Join-Path $DeploymentPayload "CarthagePOSDeployment.exe"
$PackagedTemplates = Join-Path $AppPayload "_internal\app\dashboard\templates"
$PackagedStatic = Join-Path $AppPayload "_internal\app\dashboard\static"

if (-not (Test-Path $AppExe)) {
    throw "PyInstaller did not produce $AppExe."
}
if (-not (Test-Path $DeploymentExe)) {
    throw "PyInstaller did not produce $DeploymentExe."
}
if (-not (Test-Path $PackagedTemplates)) {
    throw "Packaged dashboard templates were not found: $PackagedTemplates"
}
if (-not (Test-Path $PackagedStatic)) {
    throw "Packaged dashboard static assets were not found: $PackagedStatic"
}

$InstallerBuilt = $false
if (-not $SkipInstaller) {
    if (-not (Test-Path $InnoSetupCompiler)) {
        throw "Inno Setup 6 compiler was not found: $InnoSetupCompiler"
    }
    Invoke-Native "Inno Setup installer build" $InnoSetupCompiler @(
        "/DMyAppVersion=""$Version""",
        "/DMySourceRoot=""$ReleaseDir""",
        "/DMyOutputDir=""$InstallerOutput""",
        "installer\carthage-pos.iss"
    )
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
Invoke-Native "Release evidence generation" $Python $EvidenceArgs

Write-Host "CBOS RC build complete: $ReleaseDir"

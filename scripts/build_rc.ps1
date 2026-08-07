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

$Dirty = (& git status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $Dirty) {
    throw "RC builds require a clean committed working tree. Commit the version promotion, rerun canonical tests and build preflight, then build from that exact commit."
}

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

$CommitOutput = & git rev-parse HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve the full Git commit for HEAD."
}
$Commit = ([string]$CommitOutput).Trim()
if (-not $Commit -or $Commit -cnotmatch '^[0-9a-f]{40}$') {
    throw "Git returned a malformed full commit for HEAD."
}
$BuildRoot = Join-Path $Root "build\rc"
$ReleaseDir = Join-Path (Join-Path $Root $ReleaseRoot) "CBOS-$Version"
$VersionFile = Join-Path $BuildRoot "version_info.txt"
$PyInstallerWork = Join-Path $BuildRoot "pyinstaller"
$InstallerOutput = Join-Path $ReleaseDir "installer"
$InstallerStage = Join-Path $BuildRoot "installer-output"

if (Test-Path $BuildRoot) {
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force
}
if (Test-Path $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $BuildRoot, $ReleaseDir, $InstallerOutput, $InstallerStage | Out-Null

Invoke-Native "Unit tests" $Python @("-m", "unittest", "discover", "-s", "tests", "-v")
Invoke-Native "Whitespace validation" "git" @("diff", "--check")
Invoke-Native "PyInstaller version metadata generation" $Python @("scripts\validate_release.py", "pyinstaller-version-file", $VersionFile)
Invoke-Native "PyInstaller prerequisite check" $Python @("-m", "PyInstaller", "--version")

$RuntimeAssetJson = & $Python -m app.deployment.runtime_assets --root $Root --format json
if ($LASTEXITCODE -ne 0) {
    throw "Runtime asset validation failed before packaging."
}
[string[]]$RuntimeAssetArguments = $RuntimeAssetJson | ConvertFrom-Json
$MainEntry = (Resolve-Path "main.py").Path
$DeploymentEntry = (Resolve-Path "deployment_cli.py").Path
$UpgradeVerifierEntry = (Resolve-Path "upgrade_verifier_cli.py").Path

$Common = @(
    "--noconfirm", "--clean", "--onedir",
    "--version-file", $VersionFile,
    "--distpath", $ReleaseDir,
    "--workpath", $PyInstallerWork,
    "--specpath", $BuildRoot
)
$Common += $RuntimeAssetArguments

$Icon = "installer\assets\carthage-pos.ico"
if (Test-Path $Icon) {
    $Common += @("--icon", $Icon)
}

Invoke-Native "CarthagePOS PyInstaller build" $Python (@("-m", "PyInstaller") + $Common + @("--name", "CarthagePOS", $MainEntry))
Invoke-Native "CarthagePOSDeployment PyInstaller build" $Python (@("-m", "PyInstaller") + $Common + @("--name", "CarthagePOSDeployment", $DeploymentEntry))
Invoke-Native "Upgrade verifier PyInstaller build" $Python @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
    "--version-file", $VersionFile, "--distpath", $ReleaseDir,
    "--workpath", $PyInstallerWork, "--specpath", $BuildRoot,
    "--name", "CarthagePOSUpgradeVerifier", $UpgradeVerifierEntry
)

$AppPayload = Join-Path $ReleaseDir "CarthagePOS"
$DeploymentPayload = Join-Path $ReleaseDir "CarthagePOSDeployment"
$AppExe = Join-Path $AppPayload "CarthagePOS.exe"
$DeploymentExe = Join-Path $DeploymentPayload "CarthagePOSDeployment.exe"
$UpgradeVerifierExe = Join-Path $ReleaseDir "CarthagePOSUpgradeVerifier.exe"

if (-not (Test-Path $AppExe)) {
    throw "PyInstaller did not produce $AppExe."
}
if (-not (Test-Path $DeploymentExe)) {
    throw "PyInstaller did not produce $DeploymentExe."
}
if (-not (Test-Path $UpgradeVerifierExe)) {
    throw "PyInstaller did not produce $UpgradeVerifierExe."
}
Invoke-Native "Packaged upgrade verifier acceptance" $Python @(
    "scripts\verify_packaged_upgrade.py", $UpgradeVerifierExe
)
$InstallerBuilt = $false
if (-not $SkipInstaller) {
    if (-not (Test-Path $InnoSetupCompiler)) {
        throw "Inno Setup 6 compiler was not found: $InnoSetupCompiler"
    }
    Invoke-Native "Inno Setup installer build" $InnoSetupCompiler @(
        "/DMyAppVersion=""$Version""",
        "/DMySourceRoot=""$ReleaseDir""",
        "/DMyOutputDir=""$InstallerStage""",
        "installer\carthage-pos.iss"
    )
    $InstallerName = "CBOS-Setup-$Version.exe"
    $StagedInstaller = Join-Path $InstallerStage $InstallerName
    $FinalInstaller = Join-Path $InstallerOutput $InstallerName
    if (-not (Test-Path -LiteralPath $StagedInstaller -PathType Leaf)) {
        throw "Inno Setup did not produce $StagedInstaller."
    }
    if ((Get-Item -LiteralPath $StagedInstaller).Length -le 0) {
        throw "Inno Setup produced an empty installer: $StagedInstaller."
    }
    Copy-Item -LiteralPath $StagedInstaller -Destination $FinalInstaller -Force
    if (-not (Test-Path -LiteralPath $FinalInstaller -PathType Leaf) -or
        (Get-Item -LiteralPath $FinalInstaller).Length -le 0) {
        throw "Final RC installer is missing or empty: $FinalInstaller."
    }
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

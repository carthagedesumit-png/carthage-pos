param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDir,
    [string]$InstallDir = "${env:ProgramFiles}\Carthage Business Operating System",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$SkipHttpChecks
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Assert-Passed {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-JsonHealth {
    param([string]$Path)
    $Uri = "$BaseUrl$Path"
    try {
        return Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 10
    } catch {
        throw "Health check failed for $Uri: $($_.Exception.Message)"
    }
}

$Version = (& python "scripts\validate_release.py" version).Trim()
$ReleasePath = (Resolve-Path $ReleaseDir).Path
$ValidationJson = & python "scripts\validate_release.py" validate --release-dir $ReleasePath --require-executables
if ($LASTEXITCODE -ne 0) {
    throw "Release artifact validation failed."
}
$Validation = $ValidationJson | ConvertFrom-Json
Assert-Passed ($Validation.version -eq $Version) "Release validation version does not match $Version."

$Manifest = Join-Path $ReleasePath "release-manifest.json"
$Checksums = Join-Path $ReleasePath "checksums.txt"
Assert-Passed (Test-Path $Manifest) "Missing release manifest."
Assert-Passed (Test-Path $Checksums) "Missing release checksums."

$InstallPath = Resolve-Path -LiteralPath $InstallDir -ErrorAction SilentlyContinue
if ($InstallPath) {
    $ConfigPath = Join-Path $InstallPath.Path "config\carthage-pos.env"
    if (Test-Path $ConfigPath) {
        $ConfigText = Get-Content $ConfigPath -Raw
        Assert-Passed ($ConfigText -notmatch "admin|password123|changeme") "Configuration appears to contain a default credential."
    }
    foreach ($Directory in @("config", "logs", "backups", "licenses")) {
        $Candidate = Join-Path $InstallPath.Path $Directory
        if (Test-Path $Candidate) {
            $Probe = Join-Path $Candidate ".cbos-write-test"
            Set-Content -LiteralPath $Probe -Value "ok" -Encoding ASCII
            Remove-Item -LiteralPath $Probe -Force
        }
    }
}

if (-not $SkipHttpChecks) {
    $Live = Invoke-JsonHealth "/health/live"
    $Ready = Invoke-JsonHealth "/health/ready"
    Assert-Passed ($Live.status -eq "live") "Liveness endpoint did not report live."
    Assert-Passed ($Ready.ready -eq $true) "Readiness endpoint did not report ready."
}

Write-Host "CBOS Windows acceptance preflight passed for $Version"
Write-Host "Manual acceptance steps still required:"
Write-Host "1. Clean install with the signed setup artifact or packaged executables."
Write-Host "2. Bootstrap an administrator without a default password."
Write-Host "3. Create store, product, receive stock, complete sale, print/save receipt, run report."
Write-Host "4. Create and verify a backup, restart CBOS, and confirm data persists."
Write-Host "5. Rehearse upgrade on a copied previous-version database and preserve config/data."
Write-Host "6. Simulate failed upgrade, verify rollback backup integrity, restore, and recheck readiness."
